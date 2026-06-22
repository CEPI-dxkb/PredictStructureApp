#!/usr/bin/env perl

=head1 NAME

App-PredictStructure - BV-BRC AppService script for unified protein structure prediction

=head1 SYNOPSIS

    App-PredictStructure [--preflight] params.json

=head1 DESCRIPTION

This script implements the BV-BRC AppService interface for running protein
structure predictions via the unified predict-structure Python CLI.
It supports Boltz-2, Chai-1, AlphaFold 2, and ESMFold through a single
entry point with automatic parameter mapping.

The Perl script handles:

=over

=item * Workspace file download/upload

=item * Parameter mapping from app_spec to CLI flags

=item * Resource estimation via Python CLI preflight subcommand

=item * Prediction execution via predict-structure CLI

=item * Characterization report generation via protein_compare

=item * Result upload to workspace

=back

=cut

use strict;
use warnings;
use Carp::Always;
use Data::Dumper;
use File::Basename;
use File::Path qw(make_path);
use File::Slurp;
use File::Copy;
use File::Find;
use JSON;
use Getopt::Long;
use Try::Tiny;
use POSIX qw(strftime);

use Bio::KBase::AppService::AppScript;

$ENV{P3_LOG_LEVEL} //= 'INFO';

my $script = Bio::KBase::AppService::AppScript->new(\&run_app, \&preflight);
# Let the framework create the result folder at ${output_path}/.${output_file}/
# so the workspace output lands at the expected location.
$script->run(\@ARGV);

# ---------------------------------------------------------------------------
# Debug initialization
# ---------------------------------------------------------------------------

sub _init_debug {
    my ($params) = @_;
    if ($params->{debug}) {
        $ENV{P3_DEBUG} = 1;
        $ENV{P3_LOG_LEVEL} = 'DEBUG';
        print STDERR "Debug mode enabled (P3_DEBUG=1, P3_LOG_LEVEL=DEBUG)\n";
    }
}

# ---------------------------------------------------------------------------
# Input validation (fail fast before expensive downloads / GPU work)
# ---------------------------------------------------------------------------

sub _validate_params {
    my ($params) = @_;

    # At least one entity source must be present
    my $has_file  = $params->{input_file} || $params->{dna_file} || $params->{rna_file};
    my $has_text  = $params->{text_input} && ref($params->{text_input}) eq 'ARRAY'
                    && @{$params->{text_input}};
    my $has_ligand = $params->{ligand} && ref($params->{ligand}) eq 'ARRAY'
                     && @{$params->{ligand}};
    my $has_smiles = $params->{smiles} && ref($params->{smiles}) eq 'ARRAY'
                     && @{$params->{smiles}};
    unless ($has_file || $has_text || $has_ligand || $has_smiles) {
        die "No inputs supplied. Provide at least one of: input_file, "
          . "dna_file, rna_file, text_input, ligand, smiles.\n";
    }

    # output_path and output_file are both required. The framework creates
    # the result folder at ${output_path}/.${output_file}/ in the workspace.
    die "output_path is required.\n" unless $params->{output_path};
    die "output_file is required.\n" unless $params->{output_file};

    # Validate text_input entries
    if ($has_text) {
        my $idx = 0;
        my %valid_types = map { $_ => 1 } qw(auto protein dna rna);
        for my $entry (@{$params->{text_input}}) {
            my $seq = $entry->{sequence} // "";
            die "text_input entry $idx has an empty sequence.\n"
                unless $seq =~ /\S/;
            my $type = $entry->{type} // "auto";
            die "text_input entry $idx has invalid type '$type'; "
              . "allowed: auto, protein, dna, rna.\n"
                unless $valid_types{$type};
            $idx++;
        }
    }

    # Validate CCD ligand codes (1-3 alphanumeric)
    if ($has_ligand) {
        for my $code (@{$params->{ligand}}) {
            next unless defined $code;
            die "Invalid ligand CCD code '$code': must be 1-3 alphanumeric "
              . "characters (e.g. ATP, NAG, MAN).\n"
                unless $code =~ /^[A-Za-z0-9]{1,3}$/;
        }
    }

    # Validate SMILES strings (non-empty, basic sanity)
    if ($has_smiles) {
        for my $smi (@{$params->{smiles}}) {
            next unless defined $smi;
            die "Empty SMILES string.\n" unless $smi =~ /\S/;
        }
    }

    # Note: boltz/openfold/chai no longer require msa_file — if no MSA
    # is uploaded, build_command enables the ColabFold MSA server
    # automatically (--use-msa-server).

    print "Input validation passed\n" if $ENV{P3_DEBUG};
}


sub _peek_file_lines {
    my ($source, $n_lines) = @_;
    $n_lines //= 5;

    # $source is either a local path or a ws:// path. For workspace
    # paths we stream via p3-cat and read only the first N lines (the
    # SIGPIPE from head stops the transfer early so we don't pull the
    # entire file). For local paths we open directly.
    my @lines;
    if (-f $source) {
        open(my $fh, "<", $source) or die "Cannot open $source: $!\n";
        while (my $line = <$fh>) {
            push @lines, $line;
            last if @lines >= $n_lines;
        }
        close($fh);
    } else {
        # Assume workspace path — stream first N lines via p3-cat
        my $cmd = "p3-cat '$source' 2>/dev/null | head -n $n_lines";
        @lines = `$cmd`;
    }
    return @lines;
}


sub _validate_file_format {
    my ($source, $label, $expected_fmt) = @_;
    # $source: local path or workspace path
    # $expected_fmt: "fasta" | "msa" | undef (skip content check)

    return unless $expected_fmt;

    my @lines = _peek_file_lines($source, 5);

    unless (@lines) {
        die "$label: file is empty or unreadable ($source).\n";
    }

    my $first_content = "";
    for my $l (@lines) {
        next if $l =~ /^\s*$/;
        $first_content = $l;
        last;
    }
    chomp $first_content;

    my $ext = ($source =~ /\.([^.]+)$/) ? lc($1) : "";

    if ($expected_fmt eq "fasta") {
        # Boltz YAML pass-through
        if ($ext =~ /^(yaml|yml)$/) {
            my $joined = join("", @lines);
            die "$label: expected Boltz YAML manifest (must contain "
              . "'version' and 'sequences'), got: '$first_content'\n"
                unless $joined =~ /version/ && $joined =~ /sequences/;
        } else {
            die "$label: expected FASTA format (first non-blank line "
              . "must start with '>'), got: '$first_content'\n"
                unless $first_content =~ /^>/;
        }
    }

    if ($expected_fmt eq "msa") {
        if ($ext eq "sto") {
            die "$label: expected Stockholm format (first line must be "
              . "'# STOCKHOLM'), got: '$first_content'\n"
                unless $first_content =~ /^#\s*STOCKHOLM/;
        } else {
            die "$label: expected MSA format (first non-comment line "
              . "must start with '>' or '#'), got: '$first_content'\n"
                unless $first_content =~ /^[>#]/;
        }
    }

    print "$label format OK ($expected_fmt, ext=$ext)\n" if $ENV{P3_DEBUG};
}


# ---------------------------------------------------------------------------
# Preflight: resource estimation
# ---------------------------------------------------------------------------

=head2 preflight

Estimate resource requirements by delegating to the Python CLI's
C<preflight> subcommand. Returns a hash with cpu, memory, runtime,
storage, and policy_data for scheduling. All tools are scheduled on
the gpu2 partition; GPU-capable tools additionally request a GPU device.

=cut

sub preflight {
    my ($app, $app_def, $raw_params, $params) = @_;

    _init_debug($params);
    _validate_params($params);

    # Note: file-format validation (p3-cat peek) is NOT done here.
    # Preflight runs on the scheduler node where workspace files are
    # not accessible. The peek runs in run_app (on the worker) instead.

    my $tool = $params->{tool} // "auto";

    # Build preflight command
    my $bin = find_predict_structure_binary();
    my @cmd = ($bin, "preflight", "--tool", $tool);

    # Add device hint if we can infer it
    if ($tool eq "esmfold") {
        push @cmd, "--device", "cpu";
    }

    # MSA context for auto-resolution. If the user uploaded an MSA file,
    # signal its presence. Otherwise, signal that the MSA server is
    # available — this lets auto-select pick boltz/openfold/chai even
    # without an uploaded file.
    if ($params->{msa_file}) {
        push @cmd, "--msa", "/dev/null";
    } else {
        push @cmd, "--use-msa-server";
    }

    print STDERR "Preflight command: @cmd\n" if $ENV{P3_DEBUG};

    # Execute and parse JSON output
    my $json_out = "";
    my $rc;
    if (open(my $fh, "-|", @cmd)) {
        local $/;
        $json_out = <$fh>;
        close($fh);
        $rc = $? >> 8;
    } else {
        $rc = 1;
    }

    if ($rc != 0 || !$json_out) {
        # Fallback: use app_spec defaults
        print STDERR "Warning: preflight command failed (rc=$rc), using defaults\n";
        return _default_preflight($tool);
    }

    my $resources;
    try {
        $resources = decode_json($json_out);
    } catch {
        print STDERR "Warning: failed to parse preflight JSON: $_\n";
        return _default_preflight($tool);
    };

    my $result = {
        cpu     => $resources->{cpu} // 8,
        memory  => $resources->{memory} // "64G",
        runtime => $resources->{runtime} // 14400,
        storage => $resources->{storage} // "50G",
    };

    # Always set partition to gpu2 for proper scheduling. GPU-capable
    # tools additionally get gpu_count + constraint so SLURM allocates
    # a GPU device.
    if ($resources->{needs_gpu}) {
        $result->{policy_data} = $resources->{policy_data} // {
            gpu_count  => 1,
            partition  => 'gpu2',
            constraint => 'V100|H100|H200',
        };
    } else {
        $result->{policy_data} = {
            partition  => 'gpu2',
        };
    }

    return $result;
}

sub _default_preflight {
    my ($tool) = @_;

    if ($tool eq "esmfold") {
        return {
            cpu     => 8,
            memory  => "32G",
            runtime => 3600,
            storage => "50G",
            policy_data => {
                partition  => 'gpu2',
            },
        };
    }

    return {
        cpu     => 8,
        memory  => "64G",
        runtime => 14400,
        storage => "50G",
        policy_data => {
            gpu_count  => 1,
            partition  => 'gpu2',
            constraint => 'V100|H100|H200',
        },
    };
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

=head2 run_app

Main execution function:

1. Download input files from workspace
2. Build and run predict-structure CLI command
3. Generate characterization report via protein_compare
4. Upload results to workspace

=cut

sub _expand_ws_placeholders {
    # Replace ${WS_HOME} / ${WS_USER} in `$text` using the workspace user
    # parsed from the auth token. Keeps params files portable across users.
    #
    # Token sources, in order:
    #   1. $KB_AUTH_TOKEN env var
    #   2. $P3_TOKEN env var
    #   3. $PATRIC_TOKEN_PATH file
    #   4. ~/.patric_token
    my ($text) = @_;
    return $text unless defined $text and $text =~ /\$\{WS_/;

    my $token = $ENV{KB_AUTH_TOKEN} // $ENV{P3_TOKEN} // "";
    if (!$token) {
        my @paths = (
            $ENV{PATRIC_TOKEN_PATH},
            ($ENV{HOME} ? "$ENV{HOME}/.patric_token" : undef),
        );
        for my $p (@paths) {
            next unless $p and -f $p;
            local $/;
            open(my $fh, "<", $p) or next;
            $token = <$fh>;
            close $fh;
            chomp $token if defined $token;
            last if $token;
        }
    }

    my $user;
    for my $part (split /\|/, $token) {
        if ($part =~ /^un=(.+)$/) {
            $user = $1;
            last;
        }
    }
    unless ($user) {
        warn "Cannot expand \${WS_*} placeholders -- no auth token found ",
             "(checked KB_AUTH_TOKEN, P3_TOKEN, PATRIC_TOKEN_PATH, ~/.patric_token)\n";
        return $text;
    }
    my $home = "/$user/home";
    $text =~ s/\$\{WS_HOME\}/$home/g;
    $text =~ s/\$\{WS_USER\}/$user/g;
    return $text;
}


sub run_app {
    my ($app, $app_def, $raw_params, $params) = @_;

    _init_debug($params);

    print "Starting PredictStructure service\n";
    print STDERR "Parameters: " . Dumper($params) . "\n" if $ENV{P3_DEBUG};

    # When dispatched via GoWe's bvbrc executor, CWL File inputs arrive
    # as hash refs ({"class":"File","path":"...","location":"..."}).
    # Resolve them to a single path string. Prefer `location` — GoWe
    # sets this to a ws:// workspace URL when files have been staged to
    # the workspace for the bvbrc executor. Fall back to `path` (local
    # filesystem) for direct worker execution, then `basename`.
    for my $key (qw(input_file dna_file rna_file msa_file)) {
        my $val = $params->{$key};
        if (ref($val) eq 'HASH') {
            my $resolved = $val->{location} // $val->{path} // $val->{basename};
            # Strip file:// scheme if present (local paths don't need it)
            $resolved =~ s{^file://}{};
            $params->{$key} = $resolved;
            print "Resolved $key from CWL File object → $params->{$key}\n"
                if $ENV{P3_DEBUG};
        }
    }

    # Expand ${WS_HOME} / ${WS_USER} placeholders in workspace-bound
    # params so committed params files don't have to bake in a
    # specific user. Same expansion happens client-side in
    # scripts/instantiate_params.py and the pytest fixtures; doing it
    # here too means manual `perl App-PredictStructure.pl ... params.json`
    # invocations work without preprocessing.
    for my $key (qw(output_path input_file dna_file rna_file msa_file)) {
        $params->{$key} = _expand_ws_placeholders($params->{$key})
            if defined $params->{$key};
    }

    _validate_params($params);

    # Ensure HuggingFace model cache is usable. ESMFold loads weights via
    # the transformers library which writes to HF_HOME. The SIF bakes
    # HF_HOME=/local_databases/esmfold, but on production workers where
    # /local_databases isn't bind-mounted that path is read-only or
    # absent → OSError EROFS. We check the current HF_HOME (or the
    # default locations) and redirect to a writable path if needed.
    {
        my $hf = $ENV{HF_HOME} // "";
        my $hf_ok = $hf && -d $hf && -w $hf;

        if (!$hf_ok) {
            # Try the standard pre-cached locations
            for my $candidate ("/local_databases/cache", "/local_databases/esmfold") {
                if (-d $candidate && -w $candidate) {
                    $ENV{HF_HOME} = $candidate;
                    $hf_ok = 1;
                    print "Set HF_HOME=$candidate (pre-cached model weights)\n"
                        if $ENV{P3_DEBUG};
                    last;
                }
            }
        }

        if (!$hf_ok) {
            my $hf_tmp = ($ENV{P3_WORKDIR} // $ENV{TMPDIR} // "/tmp") . "/hf_cache";
            make_path($hf_tmp);
            $ENV{HF_HOME} = $hf_tmp;
            print STDERR "Warning: HF_HOME=$hf is not writable and "
                       . "/local_databases/cache not found; "
                       . "redirected to $hf_tmp (model download may be slow)\n";
        }

        # When a real pre-cached HF_HOME was found ($hf_ok), force the
        # transformers library offline so ESMFold loads weights straight
        # from the local cache instead of round-tripping to the Hub for
        # revision/etag validation on every from_pretrained() call (issue
        # #40). Only set this on the pre-cached path: the temp-dir
        # fallback above still needs network access to download weights.
        if ($hf_ok) {
            $ENV{HF_HUB_OFFLINE} = 1;
            print "Set HF_HUB_OFFLINE=1 (using pre-cached weights, offline)\n"
                if $ENV{P3_DEBUG};
        }
    }

    # Create working directories
    my $work_dir = $ENV{P3_WORKDIR} // $ENV{TMPDIR} // "/tmp";
    my $input_dir  = "$work_dir/input";
    my $output_dir = "$work_dir/output";

    make_path($input_dir, $output_dir);

    # Ensure the workspace output folder exists before we attempt to
    # upload results there at the end. p3-mkdir is a no-op if the
    # folder already exists; errors are non-fatal (the upload step
    # will report a clearer message if the path is truly invalid).
    if (my $ws_out = $params->{output_path}) {
        my $rc = system("p3-mkdir", $ws_out);
        if ($rc != 0) {
            print STDERR "Warning: p3-mkdir $ws_out returned rc="
                . ($rc >> 8) . "; continuing (folder may already exist)\n";
        } else {
            print "Workspace output folder ready: $ws_out\n" if $ENV{P3_DEBUG};
        }
    }

    # -----------------------------------------------------------------
    # 1. Download input files from workspace
    # -----------------------------------------------------------------

    # Resolve inputs. Multiple sources can combine in a single job:
    #   - input_file:  protein FASTA (workspace upload)
    #   - dna_file:    DNA FASTA (workspace upload)
    #   - rna_file:    RNA FASTA (workspace upload)
    #   - text_input:  inline sequences with optional type
    #   - ligand:      list of CCD codes (string list)
    #   - smiles:      list of SMILES strings (string list)
    my @input_flags;  # list of [flag, path-or-value] pairs for predict-structure

    # File-typed entity uploads
    my %file_param_flag = (
        input_file => "--protein",
        dna_file   => "--dna",
        rna_file   => "--rna",
    );
    for my $key (sort keys %file_param_flag) {
        next unless $params->{$key};
        # Peek at first lines via p3-cat before downloading the whole file
        _validate_file_format($params->{$key}, $key, "fasta");
        print "Downloading $key: $params->{$key}\n";
        my $local = download_workspace_file($app, $params->{$key}, $input_dir);
        push @input_flags, [$file_param_flag{$key}, $local];
    }

    # Inline sequences (text_input) -- grouped by type into one file per group
    if ($params->{text_input} && ref($params->{text_input}) eq 'ARRAY') {
        my %by_type;
        my $entry_idx = 0;
        for my $entry (@{$params->{text_input}}) {
            my $seq_type = $entry->{type} // "auto";
            my $seq_text = $entry->{sequence} // "";
            next unless $seq_text =~ /\S/;
            if ($seq_text !~ /^>/) {
                $seq_text = ">sequence_${entry_idx}\n${seq_text}";
            }
            push @{$by_type{$seq_type}}, $seq_text;
            $entry_idx++;
        }
        my %type_flag = (
            protein => "--protein",
            dna     => "--dna",
            rna     => "--rna",
            auto    => "--sequence",
        );
        for my $type (keys %by_type) {
            my $filepath = "$input_dir/text_${type}.fasta";
            open(my $fh, ">", $filepath) or die "Cannot write $filepath: $!\n";
            print $fh join("\n", @{$by_type{$type}}) . "\n";
            close($fh);
            push @input_flags, [$type_flag{$type} // "--sequence", $filepath];
            print "Wrote text_input ($type): $filepath\n";
        }
    }

    # Inline string lists (CCD ligands, SMILES)
    if ($params->{ligand} && ref($params->{ligand}) eq 'ARRAY') {
        for my $code (@{$params->{ligand}}) {
            next unless defined $code && $code =~ /\S/;
            push @input_flags, ["--ligand", $code];
        }
    }
    if ($params->{smiles} && ref($params->{smiles}) eq 'ARRAY') {
        for my $smi (@{$params->{smiles}}) {
            next unless defined $smi && $smi =~ /\S/;
            push @input_flags, ["--smiles", $smi];
        }
    }

    @input_flags
        or die "No inputs supplied. Provide at least one of: input_file, "
             . "dna_file, rna_file, text_input, ligand, smiles.\n";

    # Optional MSA file. Presence drives the mode -- there is no separate
    # msa_mode parameter (BV-BRC policy: external MSA servers are disabled).
    my $local_msa;
    if ($params->{msa_file}) {
        _validate_file_format($params->{msa_file}, "msa_file", "msa");
        print "Downloading MSA file: $params->{msa_file}\n";
        $local_msa = download_workspace_file($app, $params->{msa_file}, $input_dir);
    }

    # -----------------------------------------------------------------
    # 2. Build and run prediction command
    # -----------------------------------------------------------------

    my @cmd = build_command($params, \@input_flags, $output_dir, $local_msa);

    print "Executing: " . join(" ", @cmd) . "\n";

    my $rc = system(@cmd);
    if ($rc != 0) {
        my $exit_code = $rc >> 8;
        die "Prediction failed with exit code: $exit_code\n";
    }

    print "Prediction completed successfully\n";

    # -----------------------------------------------------------------
    # 3. Generate characterization report
    # -----------------------------------------------------------------

    run_report($output_dir);

    # -----------------------------------------------------------------
    # 3b. Finalize results.json + ro-crate-metadata.json
    # -----------------------------------------------------------------
    # Delegate to the Python CLI so sha256/manifest logic stays in one
    # place. The CLI re-walks the output dir (including freshly written
    # reports/) and refreshes results.json + ro-crate-metadata.json.
    # Non-fatal if it fails -- prediction artifacts still upload.
    my $bin = find_predict_structure_binary();
    my $fin_rc = system($bin, "finalize-results", $output_dir);
    if ($fin_rc != 0) {
        print STDERR "Warning: finalize-results failed (rc="
            . ($fin_rc >> 8) . "); continuing with upload\n";
    }

    # -----------------------------------------------------------------
    # 4. Upload results to workspace
    # -----------------------------------------------------------------

    # We called donot_create_result_folder(1), so the framework's
    # result_folder() is undef. Upload directly to the user-supplied
    # output_path (the user/test is already providing a versioned path).
    my $output_folder = $app->result_folder()
        // $params->{output_path}
        // die "No output_path in params and framework result_folder unset\n";

    # Clean up trailing slashes/dots in case the caller supplied them.
    $output_folder =~ s/\/+$//;
    $output_folder =~ s/\/\.$//;


    # 4a. Rewrite location URLs in results.json + metadata.json from
    # relative paths to ws:// URLs that match the upload destination.
    # Done BEFORE upload so the published results.json carries the
    # workspace URLs from the start.
    my $ws_base = "ws://$output_folder";
    my $rw_rc = system($bin, "rewrite-locations", $output_dir, "--base", $ws_base);
    if ($rw_rc != 0) {
        print STDERR "Warning: rewrite-locations failed (rc="
            . ($rw_rc >> 8) . "); locations will remain relative\n";
    }

    print "Uploading results to workspace: $output_folder\n";
    upload_results($app, $output_dir, $output_folder);

    print "PredictStructure job completed\n";
    return 0;
}

# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

=head2 build_command

Map app_spec parameters to predict-structure CLI flags.

=cut

sub build_command {
    my ($params, $input_flags, $output_dir, $local_msa) = @_;

    my $bin = find_predict_structure_binary();
    my $tool = $params->{tool} // "auto";

    # --verbose is a top-level Click option (must come BEFORE the subcommand)
    my @cmd = ($bin);
    push @cmd, "--verbose" if $ENV{P3_DEBUG};
    push @cmd, $tool;

    # Add input flags (e.g. --protein file.fasta, --dna dna.fasta, --sequence auto.fasta)
    for my $pair (@$input_flags) {
        push @cmd, $pair->[0], $pair->[1];
    }

    push @cmd, "-o", $output_dir;

    # Always use subprocess backend inside the container
    push @cmd, "--backend", "subprocess";

    # --- Shared options ---

    if (my $n = $params->{num_samples}) {
        push @cmd, "--num-samples", $n;
    }

    if (my $n = $params->{num_recycles}) {
        push @cmd, "--num-recycles", $n;
    }

    if (defined $params->{seed}) {
        push @cmd, "--seed", $params->{seed};
    }

    if (my $fmt = $params->{output_format}) {
        push @cmd, "--output-format", $fmt;
    }

    # --- MSA options ---
    #
    # If the user uploaded an MSA file, pass it directly. Otherwise, for
    # tools that benefit from MSA (boltz/openfold/chai), enable the
    # ColabFold MSA server so they fetch alignments automatically.
    # ESMFold ignores MSA; AlphaFold builds its own from local databases.

    if ($local_msa) {
        push @cmd, "--msa", $local_msa;
    } elsif ($tool !~ /^(esmfold|alphafold)$/) {
        # Enable ColabFold MSA server for boltz/openfold/chai and auto.
        # ESMFold ignores MSA; AlphaFold builds its own from local DBs.
        push @cmd, "--use-msa-server";
    }

    # --- Tool-specific options ---

    # Boltz / Chai shared options
    if ($tool eq "boltz" || $tool eq "chai") {
        if (my $steps = $params->{sampling_steps}) {
            push @cmd, "--sampling-steps", $steps;
        }
    }

    # Boltz-specific
    if ($tool eq "boltz") {
        if ($params->{use_potentials}) {
            push @cmd, "--use-potentials";
        }
    }

    # AlphaFold-specific
    if ($tool eq "alphafold") {
        my $data_dir = $params->{af2_data_dir} // "/local_databases/alphafold/databases";
        push @cmd, "--af2-data-dir", $data_dir;

        if (my $preset = $params->{af2_model_preset}) {
            push @cmd, "--af2-model-preset", $preset;
        }
        if (my $db = $params->{af2_db_preset}) {
            push @cmd, "--af2-db-preset", $db;
        }
        if (my $date = $params->{af2_max_template_date}) {
            push @cmd, "--af2-max-template-date", $date;
        }
    }

    # ESMFold-specific
    if ($tool eq "esmfold") {
        push @cmd, "--device", "cpu"
            unless _has_gpu();

        if ($params->{fp16}) {
            push @cmd, "--fp16";
        }
        if (my $cs = $params->{chunk_size}) {
            push @cmd, "--chunk-size", $cs;
        }
        if (my $mt = $params->{max_tokens_per_batch}) {
            push @cmd, "--max-tokens-per-batch", $mt;
        }
    }

    # OpenFold 3-specific
    if ($tool eq "openfold") {
        if (my $samples = $params->{num_diffusion_samples}) {
            push @cmd, "--num-diffusion-samples", $samples;
        }
        if (my $seeds = $params->{num_model_seeds}) {
            push @cmd, "--num-model-seeds", $seeds;
        }
        if (defined $params->{use_templates} && !$params->{use_templates}) {
            push @cmd, "--no-templates";
        }

        # H200 requires disabling DeepSpeed evo_attention
        my $runner = "$ENV{KB_MODULE_DIR}/test_data/openfold_bench/runner.yml";
        if (-f $runner) {
            push @cmd, "--runner-yaml", $runner;
        }
    }

    return @cmd;
}

sub _has_gpu {
    my $rc = system("nvidia-smi >/dev/null 2>&1");
    return ($rc == 0);
}

# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

=head2 run_report

Generate a characterization report from the best predicted structure
using protein_compare. Non-fatal: prediction results are still uploaded
if report generation fails.

=cut

sub run_report {
    my ($output_dir) = @_;

    my $model_pdb = "$output_dir/model_1.pdb";
    unless (-f $model_pdb) {
        print STDERR "Warning: model_1.pdb not found, skipping report generation\n";
        return;
    }

    # protein_compare characterize uses -o as a filename PREFIX and writes
    # <prefix>.html / <prefix>.json / <prefix>.pdf (not a directory). Land
    # them under reports/ in the unified layout; we copy report.html to the
    # top level afterward as the user-facing entry point.
    my $reports_dir = "$output_dir/reports";
    make_path($reports_dir);
    my $report_prefix = "$reports_dir/report";

    # Use the predict-structure conda env's python (has protein_compare),
    # not whatever 'python' is first on PATH (PATRIC runtime python lacks it).
    my $bin = find_predict_structure_binary();
    my $python = $bin;
    $python =~ s{/predict-structure$}{/python};
    $python = "python" unless -x $python;

    my @cmd = (
        $python, "-m", "protein_compare", "characterize",
        $model_pdb,
        "-o", $report_prefix,
        "--format", "all",
    );

    # Add tool-specific confidence files if available
    # Boltz / AlphaFold PAE
    my @pae_files;
    File::Find::find(
        { wanted => sub { push @pae_files, $_ if /\bpae[_.].*\.json$/ }, no_chdir => 1 },
        "$output_dir/raw_output"
    ) if -d "$output_dir/raw_output";
    if (@pae_files) {
        push @cmd, "--pae", $pae_files[0];
    }

    # Chai scores
    my @chai_scores;
    File::Find::find(
        { wanted => sub { push @chai_scores, $_ if /scores\..*\.npz$/ }, no_chdir => 1 },
        "$output_dir/raw_output"
    ) if -d "$output_dir/raw_output";
    if (@chai_scores) {
        push @cmd, "--chai-scores", $chai_scores[0];
    }

    print "Generating characterization report: " . join(" ", @cmd) . "\n";

    my $rc = system(@cmd);
    if ($rc != 0) {
        print STDERR "Warning: report generation failed (rc=" . ($rc >> 8) . "), continuing with upload\n";
        return;
    }
    print "Report generated successfully\n";

    # Copy reports/report.html to the top level as the user-facing entry
    # point. The full report set (html/json/pdf, plus any future images)
    # remains under reports/.
    my $report_html = "$reports_dir/report.html";
    if (-f $report_html) {
        copy($report_html, "$output_dir/report.html")
            or print STDERR "Warning: failed to promote report.html: $!\n";
    }
}

# ---------------------------------------------------------------------------
# Workspace helpers
# ---------------------------------------------------------------------------

=head2 download_workspace_file

Download a file from the BV-BRC workspace to a local directory.

=cut

sub download_workspace_file {
    my ($app, $ws_path, $local_dir) = @_;

    my $basename = basename($ws_path);
    my $local_path = "$local_dir/$basename";

    # If the path is local-readable inside the container (acceptance
    # tests bind-mount fixtures at /data, /tmp, etc.), copy directly.
    # BV-BRC workspace paths look like /<user>@<domain>/... which never
    # exist as local files, so this is unambiguous.
    if (-f $ws_path) {
        copy($ws_path, $local_path) or die "Local copy failed: $!\n";
        return $local_path;
    }

    if ($app && $app->can('workspace')) {
        try {
            $app->workspace->download_file($ws_path, $local_path, 1);
        } catch {
            die "Failed to download $ws_path: $_\n";
        };
    } else {
        die "File not found: $ws_path (no workspace connection)\n";
    }

    return $local_path;
}

=head2 upload_results

Upload prediction results to the BV-BRC workspace using p3-cp.

=cut

sub upload_results {
    my ($app, $local_dir, $ws_path) = @_;

    # CWL invocations set PREDICT_STRUCTURE_SKIP_UPLOAD=1 because CWL
    # collects outputs from the working directory directly; there is no
    # workspace to upload to.
    if ($ENV{PREDICT_STRUCTURE_SKIP_UPLOAD}) {
        print "Skipping workspace upload (PREDICT_STRUCTURE_SKIP_UPLOAD=1)\n";
        return;
    }

    my %type_map = (
        txt   => "txt",
        pdb   => "pdb",
        cif   => "cif",
        mmcif => "mmcif",
        json  => "json",
        html  => "html",
        npz   => "unspecified",
        png   => "png",
        svg   => "svg",
        csv   => "csv",
        fasta => "contigs",
        fa    => "contigs",
        faa   => "feature_protein_fasta",
    );

    # Use the workspace client's upload_folder directly with /. to copy
    # the CONTENTS of local_dir into ws_path (not the directory itself).
    # p3-cp -r always nests; upload_folder with /. doesn't.
    print "Uploading $local_dir/. → $ws_path\n";
    try {
        $app->workspace->upload_folder("$local_dir/.", $ws_path,
            { type_map => \%type_map, overwrite => 1 });
    } catch {
        die "Error uploading results to workspace: $_\n";
    };
}

# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------

=head2 find_predict_structure_binary

Locate the predict-structure Python CLI binary.

Search order:
1. predict-structure on PATH
2. P3_PREDICT_STRUCTURE_PATH environment variable
3. /opt/conda-predict/bin/predict-structure (container default)

=cut

sub find_predict_structure_binary {
    my $binary = "predict-structure";

    # Check PATH
    if (my $path_env = $ENV{PATH}) {
        for my $dir (split(/:/, $path_env)) {
            next unless $dir;
            my $full_path = "$dir/$binary";
            if (-x $full_path && !-d $full_path) {
                return $full_path;
            }
        }
    }

    # Check environment variable override
    if (my $ps_path = $ENV{P3_PREDICT_STRUCTURE_PATH}) {
        my $bin_path = "$ps_path/$binary";
        if (-x $bin_path) {
            return $bin_path;
        }
    }

    # Container default
    my $default = "/opt/conda-predict/bin/$binary";
    return $default;
}

__END__

=head1 AUTHOR

BV-BRC Team

=head1 LICENSE

MIT License

=cut
