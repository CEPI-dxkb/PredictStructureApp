{
    "id": "PredictStructureFull",
    "script": "App-PredictStructure",
    "label": "Protein Structure Prediction (Full / Reference)",
    "description": "Reference app spec exposing every option supported by the predict-structure CLI. Intended for advanced users and as documentation of the full surface area; the basic 'PredictStructure' spec is the recommended entry point for typical jobs. All tool-specific knobs (Boltz / OpenFold / Chai / AlphaFold / ESMFold) are surfaced here. External MSA servers (use_msa_server / msa_server_url) remain disabled by BV-BRC policy in App-PredictStructure.pl, so those fields are exposed only for direct-CLI / CWL invocations. Note that use_msa_server is silently ignored when running through this AppScript.",
    "default_memory": "64G",
    "default_cpu": 8,
    "default_runtime": 14400,
    "parameters": [
        {
            "id": "tool",
            "type": "enum",
            "enum": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"],
            "default": "auto",
            "required": 1,
            "label": "Prediction Tool",
            "desc": "Structure prediction engine. 'auto' picks the best available tool: with MSA → Boltz > OpenFold > Chai > ESMFold > AlphaFold; without MSA → ESMFold > AlphaFold."
        },

        {
            "id": "input_file",
            "type": "wsfile",
            "required": 0,
            "label": "Protein FASTA",
            "desc": "Protein FASTA file. Multi-chain by including multiple sequences. Boltz also accepts a YAML manifest."
        },
        {
            "id": "dna_file",
            "type": "wsfile",
            "required": 0,
            "label": "DNA FASTA",
            "desc": "DNA FASTA file. Tools that support DNA: Boltz-2, OpenFold 3, Chai-1."
        },
        {
            "id": "rna_file",
            "type": "wsfile",
            "required": 0,
            "label": "RNA FASTA",
            "desc": "RNA FASTA file. Tools that support RNA: Boltz-2, OpenFold 3, Chai-1."
        },
        {
            "id": "text_input",
            "type": "list",
            "required": 0,
            "label": "Inline Sequence Input",
            "desc": "One or more sequences as text (alternative to file uploads).",
            "item": {
                "id": "entry",
                "type": "object",
                "properties": [
                    {
                        "id": "type",
                        "type": "enum",
                        "enum": ["auto", "protein", "dna", "rna"],
                        "default": "auto",
                        "label": "Sequence Type"
                    },
                    {
                        "id": "sequence",
                        "type": "string",
                        "required": 1,
                        "label": "Sequence"
                    }
                ]
            }
        },
        {
            "id": "ligand",
            "type": "list",
            "required": 0,
            "label": "Ligands (CCD codes)",
            "desc": "CCD codes (1-3 alphanumeric), incl. glycans (NAG, MAN). Tools: Boltz, OpenFold, Chai.",
            "item": {"id": "ccd", "type": "string"}
        },
        {
            "id": "smiles",
            "type": "list",
            "required": 0,
            "label": "SMILES Strings",
            "desc": "SMILES strings for arbitrary small molecules. Tools: Boltz, OpenFold, Chai.",
            "item": {"id": "smiles_str", "type": "string"}
        },
        {
            "id": "msa_file",
            "type": "wsfile",
            "required": 0,
            "label": "MSA File",
            "desc": "Pre-computed MSA (.a3m, .sto). Required for Boltz, OpenFold, Chai (BV-BRC policy: external MSA servers disabled). ESMFold ignores; AlphaFold builds its own from local DBs."
        },

        {
            "id": "num_samples",
            "type": "int",
            "default": 1,
            "required": 0,
            "label": "Number of Samples",
            "desc": "Diffusion samples (Boltz / OpenFold / Chai). Maps to --diffusion_samples / --num-diffusion-samples / --num-diffn-samples respectively."
        },
        {
            "id": "num_recycles",
            "type": "int",
            "default": 3,
            "required": 0,
            "label": "Recycling Iterations",
            "desc": "Recycling iterations. Boltz: --recycling_steps. Chai: --num-trunk-recycles. ESMFold: --num-recycles. AlphaFold: implicit. OpenFold: set via runner YAML, not exposed."
        },
        {
            "id": "seed",
            "type": "int",
            "default": 42,
            "required": 0,
            "label": "Random Seed",
            "desc": "Random seed. OpenFold: --num-model-seeds. Chai: --seed. AlphaFold: --random_seed. Boltz / ESMFold: ignored (no seed param)."
        },
        {
            "id": "output_format",
            "type": "enum",
            "enum": ["pdb", "mmcif"],
            "default": "pdb",
            "required": 0,
            "label": "Output Format",
            "desc": "Primary structure output format (both PDB and mmCIF are always written; this flags the primary)."
        },
        {
            "id": "device",
            "type": "enum",
            "enum": ["gpu", "cpu"],
            "default": "gpu",
            "required": 0,
            "label": "Compute Device",
            "desc": "Compute device. ESMFold supports CPU; the others effectively require GPU."
        },

        {
            "id": "use_msa_server",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Use external MSA server (CLI only)",
            "desc": "POLICY: Ignored by App-PredictStructure.pl (external MSA servers are disabled in BV-BRC). Exposed for direct-CLI / CWL parity only. Boltz / OpenFold / Chai."
        },
        {
            "id": "msa_server_url",
            "type": "string",
            "required": 0,
            "label": "Custom MSA server URL (CLI only)",
            "desc": "POLICY: Ignored by App-PredictStructure.pl. Exposed for direct-CLI / CWL parity only."
        },

        {
            "id": "sampling_steps",
            "type": "int",
            "default": 200,
            "required": 0,
            "label": "Diffusion Sampling Steps",
            "desc": "Diffusion sampling steps. Boltz / Chai only."
        },

        {
            "id": "use_potentials",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Use Inference Potentials (Boltz only)",
            "desc": "Apply inference-time potentials for improved physical plausibility. Boltz only."
        },

        {
            "id": "no_esm_embeddings",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Disable ESM2 Embeddings (Chai only)",
            "desc": "Disable Chai's ESM2 language-model embeddings. Chai only."
        },
        {
            "id": "use_templates_server",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Use PDB Template Server (Chai only)",
            "desc": "Use Chai's PDB template server. Chai only."
        },
        {
            "id": "constraint_path",
            "type": "wsfile",
            "required": 0,
            "label": "Constraint File (Chai only)",
            "desc": "Constraint JSON file. Chai only."
        },
        {
            "id": "template_hits_path",
            "type": "wsfile",
            "required": 0,
            "label": "Template Hits File (Chai only)",
            "desc": "Pre-computed template hits file. Chai only."
        },
        {
            "id": "num_trunk_samples",
            "type": "int",
            "default": 1,
            "required": 0,
            "label": "Trunk Samples (Chai only)",
            "desc": "Trunk samples per prediction. Chai only."
        },
        {
            "id": "recycle_msa_subsample",
            "type": "int",
            "default": 0,
            "required": 0,
            "label": "Recycle MSA Subsample (Chai only)",
            "desc": "MSA rows to subsample per recycle (0 = use all). Chai only."
        },
        {
            "id": "no_low_memory",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Disable Low-Memory Mode (Chai only)",
            "desc": "Disable Chai's low-memory mode. Chai only."
        },

        {
            "id": "af2_data_dir",
            "type": "string",
            "default": "/databases",
            "required": 0,
            "label": "AlphaFold Database Directory",
            "desc": "Path to AlphaFold2 genetic databases (~2TB). AlphaFold only."
        },
        {
            "id": "af2_model_preset",
            "type": "enum",
            "enum": ["monomer", "monomer_ptm", "monomer_casp14", "multimer"],
            "default": "monomer",
            "required": 0,
            "label": "AlphaFold Model Preset",
            "desc": "AlphaFold2 model configuration. AlphaFold only."
        },
        {
            "id": "af2_db_preset",
            "type": "enum",
            "enum": ["reduced_dbs", "full_dbs"],
            "default": "reduced_dbs",
            "required": 0,
            "label": "AlphaFold Database Preset",
            "desc": "Database configuration ('reduced_dbs' uses small_bfd ~17GB; 'full_dbs' uses BFD+uniref30 ~1.8TB). AlphaFold only."
        },
        {
            "id": "af2_max_template_date",
            "type": "string",
            "default": "2022-01-01",
            "required": 0,
            "label": "AlphaFold Max Template Date",
            "desc": "Maximum PDB template release date (YYYY-MM-DD). AlphaFold only."
        },

        {
            "id": "fp16",
            "type": "bool",
            "default": false,
            "required": 0,
            "label": "Half-Precision Inference (ESMFold only)",
            "desc": "Use FP16 inference. ESMFold only."
        },
        {
            "id": "chunk_size",
            "type": "int",
            "required": 0,
            "label": "Chunk Size (ESMFold only)",
            "desc": "Chunk size for long sequences. Smaller values reduce GPU memory. ESMFold only."
        },
        {
            "id": "max_tokens_per_batch",
            "type": "int",
            "required": 0,
            "label": "Max Tokens per Batch (ESMFold only)",
            "desc": "Maximum tokens per batch for multi-sequence input. ESMFold only."
        },

        {
            "id": "num_diffusion_samples",
            "type": "int",
            "default": 5,
            "required": 0,
            "label": "Diffusion Samples (OpenFold only)",
            "desc": "Diffusion samples per query. OpenFold 3 only. (Distinct from num_samples which maps similarly across diffusion tools.)"
        },
        {
            "id": "num_model_seeds",
            "type": "int",
            "default": 1,
            "required": 0,
            "label": "Model Seeds (OpenFold only)",
            "desc": "Independent model seeds. OpenFold 3 only."
        },
        {
            "id": "use_templates",
            "type": "bool",
            "default": true,
            "required": 0,
            "label": "Use Templates (OpenFold only)",
            "desc": "Use PDB template structures. OpenFold 3 only."
        },

        {
            "id": "report_name",
            "type": "string",
            "default": "report",
            "required": 0,
            "label": "Report Name Prefix",
            "desc": "Output report filename prefix (the workflow's protein-compare step writes <prefix>.html / .json / .pdf)."
        },
        {
            "id": "report_format",
            "type": "enum",
            "enum": ["html", "pdf", "json", "both", "all"],
            "default": "all",
            "required": 0,
            "label": "Report Format",
            "desc": "Which characterization report formats to emit."
        },

        {
            "id": "output_path",
            "type": "folder",
            "required": 1,
            "label": "Output Folder",
            "desc": "Workspace folder for prediction results."
        },
        {
            "id": "output_file",
            "type": "wsfile",
            "required": 0,
            "label": "Output File Prefix",
            "desc": "Optional output filename prefix; only used when P3_DEBUG_RUN_SUBFOLDER=1."
        }
    ]
}
