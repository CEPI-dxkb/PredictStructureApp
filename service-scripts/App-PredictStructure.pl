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

    my $tool = $params->{tool} // "auto";

    # Build preflight command
    my $bin = find_predict_structure_binary();
    my @cmd = ($bin, "preflight", "--tool", $tool);

    # Add device hint if we can infer it
    if ($tool eq "esmfold") {
        push @cmd, "--device", "cpu";
    }

    # Add MSA context for auto-resolution
    my $msa_mode = $params->{msa_mode} // "none";
    if ($msa_mode eq "server") {
        push @cmd, "--use-msa-server";
    } elsif ($msa_mode eq "upload" && $params->{msa_file}) {
        push @cmd, "--msa", "/dev/null";  # existence signal only; file not available in preflight
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
            constraint => 'A100|H100|H200',
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
            constraint => 'A100|H100|H200',
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

sub run_app {
    my ($app, $app_def, $raw_params, $params) = @_;

    print "Starting PredictStructure service\n";
    print STDERR "Parameters: " . Dumper($params) . "\n" if $ENV{P3_DEBUG};

    # Create working directories
    my $work_dir = $ENV{P3_WORKDIR} // $ENV{TMPDIR} // "/tmp";
    my $input_dir  = "$work_dir/input";
    my $output_dir = "$work_dir/output";

    make_path($input_dir, $output_dir);

    # -----------------------------------------------------------------
    # 1. Download input files from workspace
    # -----------------------------------------------------------------

    # Resolve input: either input_file (workspace) or text_input (inline)
    my @input_flags;  # list of [flag, path] pairs for predict-structure

    if ($params->{input_file}) {
        print "Downloading input file: $params->{input_file}\n";
        my $local_input = download_workspace_file($app, $params->{input_file}, $input_dir);
        push @input_flags, ["--protein", $local_input];
    }
    elsif ($params->{text_input} && ref($params->{text_input}) eq 'ARRAY') {
        # Group entries by type, write each group to a file
        my %by_type;
        my $entry_idx = 0;
        for my $entry (@{$params->{text_input}}) {
            my $seq_type = $entry->{type} // "auto";
            my $seq_text = $entry->{sequence} // "";
            next unless $seq_text =~ /\S/;

            # Add FASTA header if missing
            if ($seq_text !~ /^>/) {
                $seq_text = ">sequence_${entry_idx}\n${seq_text}";
            }
            push @{$by_type{$seq_type}}, $seq_text;
            $entry_idx++;
        }

        # Write grouped files and map to CLI flags
        my %type_flag = (
            protein => "--protein",
            dna     => "--dna",
            rna     => "--rna",
            auto    => "--sequence",
        );

        for my $type (keys %by_type) {
            my $filename = "${type}.fasta";
            my $filepath = "$input_dir/$filename";
            open(my $fh, ">", $filepath) or die "Cannot write $filepath: $!\n";
            print $fh join("\n", @{$by_type{$type}}) . "\n";
            close($fh);

            my $flag = $type_flag{$type} // "--sequence";
            push @input_flags, [$flag, $filepath];
            print "Wrote text_input ($type): $filepath\n";
        }
    }
    else {
        die "Either input_file or text_input is required\n";
    }

    # Optional MSA file
    my $local_msa;
    if ($params->{msa_mode} && $params->{msa_mode} eq "upload" && $params->{msa_file}) {
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
    # place. This also relocates report.html/.json/.pdf into report/ for
    # the unified layout. Non-fatal if it fails -- prediction artifacts
    # still upload.
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

    my $msa_mode = $params->{msa_mode} // "none";

    if ($msa_mode eq "server") {
        push @cmd, "--use-msa-server";
        if (my $url = $params->{msa_server_url}) {
            push @cmd, "--msa-server-url", $url;
        }
    } elsif ($msa_mode eq "upload" && $local_msa) {
        push @cmd, "--msa", $local_msa;
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
    # <prefix>.html / <prefix>.json / <prefix>.pdf (not a directory). Use
    # "<output_dir>/report" so the files land as report.html / report.json
    # / report.pdf alongside the prediction artifacts.
    my $report_prefix = "$output_dir/report";

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
    } else {
        print "Report generated successfully\n";
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

    if ($app && $app->can('workspace')) {
        try {
            $app->workspace->download_file($ws_path, $local_path, 1);
        } catch {
            die "Failed to download $ws_path: $_\n";
        };
    } else {
        # Fallback for testing without workspace connection
        if (-f $ws_path) {
            copy($ws_path, $local_path) or die "Copy failed: $!\n";
        } else {
            die "File not found: $ws_path\n";
        }
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
