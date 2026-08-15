{
  "id": "PredictStructure",
  "label": "Protein Structure Prediction (Merged UI Reference)",
  "description": "All options across all tools with section/tools/tier annotations for UI rendering. Custom keys (section, tools, tier) are ignored by the BV-BRC AppService framework; they are consumed by the UI to show/hide fields based on tool selection.",
  "parameters": [

    {"id": "tool", "type": "enum", "enum": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "default": "auto", "required": 1,
     "label": "Prediction Tool", "desc": "Structure prediction engine. 'auto' picks Boltz (highest quality) by default; MSA fetched via ColabFold server automatically.",
     "section": "core", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 1},

    {"id": "input_file", "type": "wsfile", "required": 0,
     "label": "Protein FASTA", "desc": "Protein sequence(s) in FASTA format. Multi-chain complexes: include multiple sequences in one file.",
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 1},

    {"id": "dna_file", "type": "wsfile", "required": 0,
     "label": "DNA FASTA", "desc": "DNA sequence(s) in FASTA format.",
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai"], "tier": 2},

    {"id": "rna_file", "type": "wsfile", "required": 0,
     "label": "RNA FASTA", "desc": "RNA sequence(s) in FASTA format.",
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai"], "tier": 2},

    {"id": "ligand", "type": "list", "required": 0,
     "label": "Ligands (CCD codes)", "desc": "Ligand CCD codes, 1-3 or exactly 5 alphanumeric (e.g. ATP, NAG, A1H1F); 4-character codes do not exist. Glycans use CCD codes here too, one code per monosaccharide.",
     "item": {"id": "ccd_code", "type": "string"},
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai"], "tier": 2},

    {"id": "smiles", "type": "list", "required": 0,
     "label": "SMILES Strings", "desc": "SMILES strings for arbitrary small molecules.",
     "item": {"id": "smiles_str", "type": "string"},
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai"], "tier": 2},

    {"id": "msa_file", "type": "wsfile", "required": 0,
     "label": "MSA File", "desc": "Pre-computed MSA (.a3m, .sto). Optional -- ColabFold server fetches MSA automatically if not provided. Upload overrides the server.",
     "section": "inputs", "tools": ["auto", "boltz", "openfold", "chai"], "tier": 2},

    {"id": "output_path", "type": "folder", "required": 1,
     "label": "Output Folder", "desc": "Workspace folder for prediction results.",
     "section": "core", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 1},

    {"id": "output_file", "type": "wsfile", "required": 1,
     "label": "Job Name", "desc": "Output name. Results land at output_path/.output_file/ in the workspace.",
     "section": "core", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 1},

    {"id": "num_samples", "type": "int", "default": 1, "required": 0,
     "label": "Number of Samples", "desc": "Structure samples to generate. More samples give diversity at the cost of runtime.",
     "section": "shared", "tools": ["boltz", "openfold", "chai"], "tier": 2},

    {"id": "output_format", "type": "enum", "enum": ["pdb", "mmcif"], "default": "pdb", "required": 0,
     "label": "Output Format", "desc": "Primary structure output format. Both PDB and mmCIF are always generated.",
     "section": "shared", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 2},

    {"id": "num_recycles", "type": "int", "default": 3, "required": 0,
     "label": "Recycling Iterations", "desc": "Recycling iterations for structure refinement.",
     "section": "shared", "tools": ["boltz", "chai", "esmfold"], "tier": 3},

    {"id": "seed", "type": "int", "default": 42, "required": 0,
     "label": "Random Seed", "desc": "Random seed for reproducibility.",
     "section": "shared", "tools": ["openfold", "chai", "alphafold"], "tier": 3},

    {"id": "debug", "type": "bool", "default": false, "required": 0,
     "label": "Debug Mode", "desc": "Enable verbose debug logging.",
     "section": "shared", "tools": ["auto", "boltz", "openfold", "chai", "alphafold", "esmfold"], "tier": 3},

    {"id": "sampling_steps", "type": "int", "default": 200, "required": 0,
     "label": "Diffusion Sampling Steps", "desc": "Number of diffusion sampling steps. Higher values may improve quality.",
     "section": "boltz", "tools": ["boltz", "chai"], "tier": 3},

    {"id": "use_potentials", "type": "bool", "default": false, "required": 0,
     "label": "Use Inference Potentials", "desc": "Apply inference-time potentials for improved physical plausibility.",
     "section": "boltz", "tools": ["boltz"], "tier": 3},

    {"id": "no_esm_embeddings", "type": "bool", "default": false, "required": 0,
     "label": "Disable ESM2 Embeddings", "desc": "Disable ESM2 language model embeddings.",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "use_templates_server", "type": "bool", "default": false, "required": 0,
     "label": "Use PDB Template Server", "desc": "Fetch PDB templates from Chai's template server.",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "constraint_path", "type": "wsfile", "required": 0,
     "label": "Constraint File", "desc": "Constraint JSON file for guided prediction.",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "template_hits_path", "type": "wsfile", "required": 0,
     "label": "Template Hits File", "desc": "Pre-computed template hits file.",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "num_trunk_samples", "type": "int", "default": 1, "required": 0,
     "label": "Trunk Samples", "desc": "Trunk samples per prediction.",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "recycle_msa_subsample", "type": "int", "default": 0, "required": 0,
     "label": "Recycle MSA Subsample", "desc": "MSA rows to subsample per recycle (0 = use all).",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "no_low_memory", "type": "bool", "default": false, "required": 0,
     "label": "Disable Low-Memory Mode", "desc": "Disable low-memory mode (uses more GPU RAM for speed).",
     "section": "chai", "tools": ["chai"], "tier": 3},

    {"id": "num_diffusion_samples", "type": "int", "default": 5, "required": 0,
     "label": "Diffusion Samples", "desc": "Diffusion samples per query.",
     "section": "openfold", "tools": ["openfold"], "tier": 3},

    {"id": "num_model_seeds", "type": "int", "default": 1, "required": 0,
     "label": "Model Seeds", "desc": "Independent model seeds.",
     "section": "openfold", "tools": ["openfold"], "tier": 3},

    {"id": "use_templates", "type": "bool", "default": true, "required": 0,
     "label": "Use Templates", "desc": "Use PDB template structures for improved accuracy.",
     "section": "openfold", "tools": ["openfold"], "tier": 3},

    {"id": "af2_data_dir", "type": "string", "default": "/local_databases/alphafold/databases", "required": 0,
     "label": "AlphaFold Database Directory", "desc": "Path to AlphaFold2 genetic databases (~2TB).",
     "section": "alphafold", "tools": ["alphafold"], "tier": 3},

    {"id": "af2_model_preset", "type": "enum", "enum": ["monomer", "monomer_ptm", "monomer_casp14", "multimer"], "default": "monomer", "required": 0,
     "label": "AlphaFold Model Preset", "desc": "Model configuration. 'monomer' for single chains, 'multimer' for complexes.",
     "section": "alphafold", "tools": ["alphafold"], "tier": 3},

    {"id": "af2_db_preset", "type": "enum", "enum": ["reduced_dbs", "full_dbs"], "default": "reduced_dbs", "required": 0,
     "label": "AlphaFold Database Preset", "desc": "Database configuration. 'reduced_dbs' (~17GB) vs 'full_dbs' (~1.8TB).",
     "section": "alphafold", "tools": ["alphafold"], "tier": 3},

    {"id": "af2_max_template_date", "type": "string", "default": "2022-01-01", "required": 0,
     "label": "Max Template Date", "desc": "Maximum PDB template release date (YYYY-MM-DD).",
     "section": "alphafold", "tools": ["alphafold"], "tier": 3},

    {"id": "fp16", "type": "bool", "default": false, "required": 0,
     "label": "Half-Precision (FP16)", "desc": "Use FP16 inference to reduce memory and increase speed.",
     "section": "esmfold", "tools": ["esmfold"], "tier": 3},

    {"id": "chunk_size", "type": "int", "required": 0,
     "label": "Chunk Size", "desc": "Chunk size for long sequences. Smaller values reduce GPU memory.",
     "section": "esmfold", "tools": ["esmfold"], "tier": 3},

    {"id": "max_tokens_per_batch", "type": "int", "required": 0,
     "label": "Max Tokens per Batch", "desc": "Maximum tokens per batch for multi-sequence input.",
     "section": "esmfold", "tools": ["esmfold"], "tier": 3}
  ]
}
