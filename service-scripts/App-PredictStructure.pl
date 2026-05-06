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
# Opt out of the framework's automatic result-folder creation. It would
# create <output_path>/.<output_file>/ (or <output_path>/ with no
# output_file), which makes p3-cp -r on upload nest our results under an
# extra <output>/ subdir. We manage the upload path ourselves.
$script->donot_create_result_folder(1);
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
# Preflight: resource estimation
# ---------------------------------------------------------------------------

=head2 preflight

Estimate resource requirements by delegating to the Python CLI's
C<preflight> subcommand. Returns a hash with cpu, memory, runtime,
storage, and optional policy_data for GPU scheduling.

ESMFold does not require a GPU, so policy_data is omitted for it.

=cut

sub preflight {
    my ($app, $app_def, $raw_params, $params) = @_;

    _init_debug($params);

    my $tool = $params->{tool} // "auto";

    # Build preflight command
    my $bin = find_predict_structure_binary();
    my @cmd = ($bin, "preflight", "--tool", $tool);

    # Add device hint if we can infer it
    if ($tool eq "esmfold") {
        push @cmd, "--device", "cpu";
    }

    # Add MSA context for auto-resolution: presence of msa_file signals to
    # the auto-selector that an MSA will be available, so it can pick a
    # tool that requires one (boltz/openfold/chai). The actual file isn't
    # downloaded here -- a placeholder path is enough.
    if ($params->{msa_file}) {
        push @cmd, "--msa", "/dev/null";
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

    # Add GPU policy only if the tool needs it
    if ($resources->{needs_gpu}) {
        $result->{policy_data} = $resources->{policy_data} // {
            gpu_count  => 1,
            partition  => 'gpu2',
            constraint => 'V100|H100|H200',
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

    # By default results are uploaded flat into $output_folder so the
    # caller controls the final layout (typically via a versioned
    # output_path). Set P3_DEBUG_RUN_SUBFOLDER=1 to nest each run under a
    # timestamped subfolder (useful when debugging multiple runs sharing
    # one output_path).
    if ($ENV{P3_DEBUG_RUN_SUBFOLDER}) {
        my $output_base = $params->{output_file} // "predict_structure_result";
        my $timestamp = POSIX::strftime("%Y%m%d_%H%M%S", localtime);
        my $task_id = $app->{task_id} // "unknown";
        my $run_folder = "${output_base}_${timestamp}_${task_id}";
        $output_folder = "$output_folder/$run_folder";
    }

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

    my @cmd = ($bin, $tool);

    # Add input flags (e.g. --protein file.fasta, --dna dna.fasta, --sequence auto.fasta)
    for my $pair (@$input_flags) {
        push @cmd, $pair->[0], $pair->[1];
    }

    push @cmd, "-o", $output_dir;

    # Always use subprocess backend inside the container
    push @cmd, "--backend", "subprocess";

    # Verbose logging when debug is on
    push @cmd, "--verbose" if $ENV{P3_DEBUG};

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
    # Presence of $local_msa drives the mode (no separate msa_mode flag).
    # BV-BRC policy: external MSA servers are disabled. Boltz / OpenFold
    # / Chai without an MSA fall back to a dummy single-sequence -> unusable
    # predictions, so we hard-error before invocation.

    if ($local_msa) {
        push @cmd, "--msa", $local_msa;
    }

    if ($tool =~ /^(boltz|openfold|chai)$/ && !$local_msa) {
        die "$tool requires an MSA upload (msa_file). "
          . "External MSA servers are disabled by BV-BRC policy. "
          . "For MSA-free prediction use esmfold; for local-database MSA "
          . "use alphafold.\n";
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
        my $data_dir = $params->{af2_data_dir} // "/databases";
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

    my @mapping = (
        '--map-suffix' => "txt=txt",
        '--map-suffix' => "pdb=pdb",
        '--map-suffix' => "cif=cif",
        '--map-suffix' => "mmcif=mmcif",
        '--map-suffix' => "json=json",
        '--map-suffix' => "html=html",
        '--map-suffix' => "npz=unspecified",
        '--map-suffix' => "png=png",
        '--map-suffix' => "svg=svg",
        '--map-suffix' => "csv=csv",
        '--map-suffix' => "fasta=contigs",
        '--map-suffix' => "fa=contigs",
        '--map-suffix' => "faa=feature_protein_fasta",
    );

    my @cmd = ("p3-cp", "--overwrite", "-r", @mapping, $local_dir, "ws:$ws_path");
    print "Upload: @cmd\n";
    my $rc = system(@cmd);
    $rc == 0 or die "Error copying data to workspace\n";
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
