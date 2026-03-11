import { useState, useCallback } from "react";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis } from "recharts";

// ─── Color palette (matches our slide deck) ──────────────────────
const C = {
  navy: "#0F2027",
  teal: "#2C5364",
  accent: "#00B4D8",
  accentLight: "#90E0EF",
  white: "#FFFFFF",
  offWhite: "#F0F4F8",
  gray100: "#F1F5F9",
  gray200: "#E2E8F0",
  gray300: "#CBD5E1",
  gray400: "#94A3B8",
  gray500: "#64748B",
  gray700: "#334155",
  gray900: "#0F172A",
  green: "#10B981",
  greenLight: "#D1FAE5",
  amber: "#F59E0B",
  amberLight: "#FEF3C7",
  red: "#EF4444",
  redLight: "#FEE2E2",
  blue: "#3B82F6",
  blueLight: "#DBEAFE",
  purple: "#8B5CF6",
  purpleLight: "#EDE9FE",
};

// ─── Mock data ───────────────────────────────────────────────────
const TOOLS = [
  { id: "auto", name: "Auto-Select", desc: "Automatically choose the best tool based on input", icon: "✦" },
  { id: "boltz", name: "Boltz-2", desc: "Diffusion-based, supports ligands & DNA/RNA", icon: "⚛" },
  { id: "chai", name: "Chai-1", desc: "Hybrid architecture, strong multimer support", icon: "🧬" },
  { id: "alphafold", name: "AlphaFold 2", desc: "Co-evolution based, gold standard", icon: "🔬" },
  { id: "esmfold", name: "ESMFold", desc: "Fast single-sequence, no MSA needed", icon: "⚡" },
];

const MOCK_RESULTS = {
  jobId: "PSP-2026-00847",
  tool: "Boltz-2",
  status: "completed",
  runtime: "1h 23m",
  submitted: "2026-03-05 09:14 UTC",
  completed: "2026-03-05 10:37 UTC",
  inputFile: "crambin_1CRN.fasta",
  sequenceLength: 46,
  numSamples: 5,
  outputFormat: "PDB + mmCIF",
  plddt_mean: 92.4,
  ptm: 0.89,
  iptm: null,
  perResidue: Array.from({ length: 46 }, (_, i) => ({
    residue: i + 1,
    plddt: 70 + Math.random() * 28 + (i > 10 && i < 35 ? 5 : 0),
    name: ["T","H","R","C","P","S","I","V","A","R","S","N","F","N","V","C","R","L","P","G","T","P","E","A","I","C","A","T","Y","T","G","C","I","I","I","P","G","A","T","C","P","G","D","Y","A","N"][i] || "X",
  })),
  models: [
    { rank: 1, plddt: 92.4, ptm: 0.89, file: "model_1.pdb" },
    { rank: 2, plddt: 91.1, ptm: 0.87, file: "model_2.pdb" },
    { rank: 3, plddt: 88.7, ptm: 0.84, file: "model_3.pdb" },
    { rank: 4, plddt: 86.2, ptm: 0.81, file: "model_4.pdb" },
    { rank: 5, plddt: 83.9, ptm: 0.78, file: "model_5.pdb" },
  ],
  toolComparison: [
    { tool: "Boltz-2", plddt: 92.4, ptm: 0.89, runtime: 83 },
    { tool: "Chai-1", plddt: 90.1, ptm: 0.86, runtime: 67 },
    { tool: "AlphaFold 2", plddt: 94.2, ptm: 0.91, runtime: 240 },
    { tool: "ESMFold", plddt: 85.3, ptm: 0.74, runtime: 12 },
  ],
  radarData: [
    { metric: "pLDDT", Boltz: 92, Chai: 90, AlphaFold: 94, ESMFold: 85 },
    { metric: "pTM", Boltz: 89, Chai: 86, AlphaFold: 91, ESMFold: 74 },
    { metric: "Speed", Boltz: 60, Chai: 70, AlphaFold: 30, ESMFold: 95 },
    { metric: "Multimer", Boltz: 90, Chai: 85, AlphaFold: 95, ESMFold: 20 },
    { metric: "Ligand", Boltz: 95, Chai: 40, AlphaFold: 30, ESMFold: 10 },
  ],
};

// ─── Reusable components ─────────────────────────────────────────

function Badge({ color, children }) {
  const colors = {
    green: { bg: C.greenLight, text: C.green },
    amber: { bg: C.amberLight, text: C.amber },
    red: { bg: C.redLight, text: C.red },
    blue: { bg: C.blueLight, text: C.blue },
    purple: { bg: C.purpleLight, text: C.purple },
    gray: { bg: C.gray200, text: C.gray500 },
  };
  const s = colors[color] || colors.gray;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", padding: "2px 10px",
      borderRadius: 12, fontSize: 12, fontWeight: 600,
      backgroundColor: s.bg, color: s.text,
    }}>{children}</span>
  );
}

function Card({ children, style, onClick, hoverable }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: C.white, borderRadius: 12,
        border: `1px solid ${hovered && hoverable ? C.accent : C.gray200}`,
        boxShadow: hovered && hoverable
          ? `0 4px 16px rgba(0,180,216,0.15)`
          : `0 1px 3px rgba(0,0,0,0.06)`,
        transition: "all 0.2s ease",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >{children}</div>
  );
}

function SectionHeader({ title, subtitle, action }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 16 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: C.gray900 }}>{title}</h2>
        {subtitle && <p style={{ margin: "2px 0 0", fontSize: 13, color: C.gray400 }}>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

function StatBox({ label, value, sub, color }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 11, color: C.gray400, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 800, color: color || C.gray900 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.gray400 }}>{sub}</div>}
    </div>
  );
}

// ─── Job Submission Form ─────────────────────────────────────────

function SubmissionForm({ onSubmit }) {
  const [tool, setTool] = useState("auto");
  const [inputMethod, setInputMethod] = useState("paste");
  const [sequence, setSequence] = useState(">1CRN_Crambin\nTTCCPSIVARSNFNVCRLPGTPEAICATYTGCIIIPGATCPGDYAN");
  const [numSamples, setNumSamples] = useState(5);
  const [numRecycles, setNumRecycles] = useState(3);
  const [outputFormat, setOutputFormat] = useState("both");
  const [msaMode, setMsaMode] = useState("none"); // "none" | "server" | "upload"
  const [msaUploadMethod, setMsaUploadMethod] = useState("file"); // "file" | "workspace"
  const [advanced, setAdvanced] = useState(false);

  const selectedTool = TOOLS.find(t => t.id === tool);

  return (
    <div style={{ maxWidth: 880, margin: "0 auto" }}>
      {/* Header */}
      <div style={{
        background: `linear-gradient(135deg, ${C.navy} 0%, ${C.teal} 100%)`,
        borderRadius: "16px 16px 0 0", padding: "28px 32px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ fontSize: 28 }}>🧪</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.white }}>
              Predict Structure
            </h1>
            <p style={{ margin: "2px 0 0", fontSize: 13, color: C.accentLight }}>
              Unified protein structure prediction — Boltz-2 · Chai-1 · AlphaFold 2 · ESMFold
            </p>
          </div>
        </div>
      </div>

      <Card style={{ borderRadius: "0 0 16px 16px", padding: 0 }}>
        <div style={{ padding: "24px 32px" }}>

          {/* ── Tool Selection ── */}
          <SectionHeader title="Prediction Tool" subtitle="Choose a tool or let the system auto-select based on your input" />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 28 }}>
            {TOOLS.map(t => (
              <div
                key={t.id}
                onClick={() => setTool(t.id)}
                style={{
                  padding: "14px 10px", borderRadius: 10, cursor: "pointer",
                  textAlign: "center", transition: "all 0.15s ease",
                  border: `2px solid ${tool === t.id ? C.accent : C.gray200}`,
                  background: tool === t.id ? `${C.accent}10` : C.white,
                }}
              >
                <div style={{ fontSize: 22, marginBottom: 4 }}>{t.icon}</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: tool === t.id ? C.accent : C.gray700 }}>{t.name}</div>
                <div style={{ fontSize: 10, color: C.gray400, marginTop: 2, lineHeight: 1.3 }}>{t.desc}</div>
              </div>
            ))}
          </div>

          {/* ── Input ── */}
          <SectionHeader title="Input Sequence" subtitle="Upload a FASTA file or paste your sequence directly" />
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            {[["paste", "Paste Sequence"], ["upload", "Upload File"], ["workspace", "From Workspace"]].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setInputMethod(id)}
                style={{
                  padding: "6px 16px", borderRadius: 8, border: "none", cursor: "pointer",
                  fontSize: 13, fontWeight: 500, transition: "all 0.15s",
                  background: inputMethod === id ? C.accent : C.gray100,
                  color: inputMethod === id ? C.white : C.gray500,
                }}
              >{label}</button>
            ))}
          </div>
          {inputMethod === "paste" ? (
            <textarea
              value={sequence}
              onChange={e => setSequence(e.target.value)}
              placeholder=">protein_name\nMASEQUENCE..."
              style={{
                width: "100%", height: 100, padding: 12, borderRadius: 8, fontSize: 13,
                fontFamily: "'SF Mono', 'Fira Code', monospace", resize: "vertical",
                border: `1px solid ${C.gray200}`, background: C.gray100,
                boxSizing: "border-box", outline: "none", color: C.gray700,
              }}
            />
          ) : inputMethod === "upload" ? (
            <div style={{
              padding: 32, borderRadius: 8, border: `2px dashed ${C.gray300}`,
              textAlign: "center", color: C.gray400, fontSize: 13, background: C.gray100,
            }}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>📁</div>
              Drop .fasta, .fa, .yaml file here or <span style={{ color: C.accent, cursor: "pointer", textDecoration: "underline" }}>browse</span>
            </div>
          ) : (
            <div style={{
              padding: 16, borderRadius: 8, border: `1px solid ${C.gray200}`, background: C.gray100,
              display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: C.gray500,
            }}>
              <span style={{ fontSize: 18 }}>📂</span>
              <span>/user@bvbrc/home/StructurePrediction/</span>
              <button style={{
                marginLeft: "auto", padding: "4px 12px", borderRadius: 6, border: "none",
                background: C.accent, color: C.white, fontSize: 12, cursor: "pointer",
              }}>Select File</button>
            </div>
          )}

          {/* ── Parameters ── */}
          <div style={{ marginTop: 28 }}>
            <SectionHeader title="Parameters" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: C.gray500, marginBottom: 4 }}>
                  Number of Samples
                </label>
                <input
                  type="number" min={1} max={25} value={numSamples}
                  onChange={e => setNumSamples(+e.target.value)}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: 8, fontSize: 14,
                    border: `1px solid ${C.gray200}`, outline: "none", boxSizing: "border-box",
                  }}
                />
                <div style={{ fontSize: 10, color: C.gray400, marginTop: 2 }}>
                  {tool === "esmfold" ? "N/A for ESMFold (deterministic)" : "More samples = better coverage, slower"}
                </div>
              </div>
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: C.gray500, marginBottom: 4 }}>
                  Recycling Steps
                </label>
                <input
                  type="number" min={1} max={20} value={numRecycles}
                  onChange={e => setNumRecycles(+e.target.value)}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: 8, fontSize: 14,
                    border: `1px solid ${C.gray200}`, outline: "none", boxSizing: "border-box",
                  }}
                />
                <div style={{ fontSize: 10, color: C.gray400, marginTop: 2 }}>Default: 3 (ESMFold: 4)</div>
              </div>
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: C.gray500, marginBottom: 4 }}>
                  Output Format
                </label>
                <select
                  value={outputFormat}
                  onChange={e => setOutputFormat(e.target.value)}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: 8, fontSize: 14,
                    border: `1px solid ${C.gray200}`, outline: "none", background: C.white, boxSizing: "border-box",
                  }}
                >
                  <option value="both">PDB + mmCIF</option>
                  <option value="pdb">PDB only</option>
                  <option value="cif">mmCIF only</option>
                </select>
              </div>
            </div>

            {/* MSA Section — hidden for ESMFold */}
            {tool !== "esmfold" && (
              <div style={{ marginTop: 20 }}>
                <SectionHeader title="Multiple Sequence Alignment" subtitle="Provide precomputed MSA or generate one server-side. Supported formats: A3M, Stockholm, Parquet" />
                <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                  {[["none", "No MSA"], ["server", "MSA Server"], ["upload", "Upload MSA"]].map(([id, label]) => (
                    <button
                      key={id}
                      onClick={() => setMsaMode(id)}
                      style={{
                        padding: "6px 16px", borderRadius: 8, border: "none", cursor: "pointer",
                        fontSize: 13, fontWeight: 500, transition: "all 0.15s",
                        background: msaMode === id ? C.accent : C.gray100,
                        color: msaMode === id ? C.white : C.gray500,
                      }}
                    >{label}</button>
                  ))}
                </div>

                {/* No MSA */}
                {msaMode === "none" && (
                  <div style={{ padding: "14px 16px", borderRadius: 8, background: C.gray100, border: `1px solid ${C.gray200}`, display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ fontSize: 20 }}>🚫</div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: C.gray700 }}>No MSA</div>
                      <div style={{ fontSize: 11, color: C.gray400 }}>Run prediction without multiple sequence alignment. Boltz and Chai can still produce good results for well-studied proteins.</div>
                    </div>
                  </div>
                )}

                {/* MSA Server */}
                {msaMode === "server" && (
                  <div style={{ padding: "14px 16px", borderRadius: 8, background: C.gray100, border: `1px solid ${C.gray200}` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                      <div style={{ fontSize: 20 }}>🌐</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: C.gray700 }}>MSA Server</div>
                        <div style={{ fontSize: 11, color: C.gray400 }}>Compute MSA server-side using ColabFold MMseqs2 (Boltz, Chai) or jackhmmer (AlphaFold)</div>
                      </div>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 8 }}>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>Database</label>
                        <select style={{ width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13, border: `1px solid ${C.gray200}`, marginTop: 4, background: C.white, boxSizing: "border-box" }}>
                          <option>Auto (tool default)</option>
                          <option>UniRef30 + ColabDB</option>
                          <option>UniRef90 + BFD</option>
                        </select>
                      </div>
                      <div>
                        <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>Max sequences</label>
                        <input type="number" placeholder="Default" style={{ width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13, border: `1px solid ${C.gray200}`, marginTop: 4, boxSizing: "border-box" }} />
                      </div>
                    </div>
                  </div>
                )}

                {/* Upload MSA */}
                {msaMode === "upload" && (
                  <div style={{ padding: "14px 16px", borderRadius: 8, background: C.gray100, border: `1px solid ${C.gray200}` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                      <div style={{ fontSize: 20 }}>📂</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: C.gray700 }}>Upload MSA</div>
                        <div style={{ fontSize: 11, color: C.gray400 }}>Provide a precomputed alignment file (.a3m, .sto, .pqt). Chai requires Parquet; adapter converts A3M automatically.</div>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                      {[["file", "Upload File"], ["workspace", "From Workspace"]].map(([id, label]) => (
                        <button
                          key={id}
                          onClick={() => setMsaUploadMethod(id)}
                          style={{
                            padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer",
                            fontSize: 12, fontWeight: 500, transition: "all 0.15s",
                            background: msaUploadMethod === id ? C.accent : C.white,
                            color: msaUploadMethod === id ? C.white : C.gray500,
                          }}
                        >{label}</button>
                      ))}
                    </div>
                    {msaUploadMethod === "file" ? (
                      <div style={{ padding: 24, borderRadius: 8, border: `2px dashed ${C.gray300}`, textAlign: "center", color: C.gray400, fontSize: 13, background: C.white }}>
                        <div style={{ fontSize: 24, marginBottom: 6 }}>📁</div>
                        Drop .a3m, .sto, or .pqt file here or <span style={{ color: C.accent, cursor: "pointer", textDecoration: "underline" }}>browse</span>
                      </div>
                    ) : (
                      <div style={{ padding: "12px 14px", borderRadius: 8, border: `1px solid ${C.gray200}`, background: C.white, display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: C.gray500 }}>
                        <span style={{ fontSize: 18 }}>📂</span>
                        <span>/user@bvbrc/home/MSA/</span>
                        <button style={{ marginLeft: "auto", padding: "4px 12px", borderRadius: 6, border: "none", background: C.accent, color: C.white, fontSize: 12, cursor: "pointer" }}>Select File</button>
                      </div>
                    )}
                    <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 6, background: C.blueLight, fontSize: 11, color: C.blue, display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontWeight: 700 }}>ℹ</span> A3M files will be auto-converted to Parquet for Chai. Boltz injects MSA into YAML input.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Advanced toggle ── */}
          <div style={{ marginTop: 20 }}>
            <button
              onClick={() => setAdvanced(!advanced)}
              style={{
                background: "none", border: "none", cursor: "pointer",
                fontSize: 13, color: C.accent, fontWeight: 500, padding: 0,
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              <span style={{ transform: advanced ? "rotate(90deg)" : "rotate(0)", transition: "0.2s", display: "inline-block" }}>▶</span>
              Advanced / Tool-Specific Options
            </button>
            {advanced && (
              <div style={{
                marginTop: 12, padding: 16, borderRadius: 8, background: C.gray100,
                border: `1px solid ${C.gray200}`,
              }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>Sampling Steps (Boltz/Chai)</label>
                    <input
                      type="number" defaultValue={200}
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13,
                        border: `1px solid ${C.gray200}`, marginTop: 4, boxSizing: "border-box",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>Random Seed</label>
                    <input
                      type="number" placeholder="Optional"
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13,
                        border: `1px solid ${C.gray200}`, marginTop: 4, boxSizing: "border-box",
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>Device</label>
                    <select
                      defaultValue="auto"
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13,
                        border: `1px solid ${C.gray200}`, marginTop: 4, background: C.white, boxSizing: "border-box",
                      }}
                    >
                      <option value="auto">Auto-detect GPU</option>
                      <option value="cuda:0">cuda:0</option>
                      <option value="cuda:1">cuda:1</option>
                      <option value="cpu">CPU only</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: 11, fontWeight: 600, color: C.gray500 }}>
                      Pass-through flags <Badge color="gray">--{tool === "auto" ? "tool" : tool}-*</Badge>
                    </label>
                    <input
                      type="text" placeholder={`e.g. --${tool === "auto" ? "boltz" : tool}-use-potentials`}
                      style={{
                        width: "100%", padding: "6px 10px", borderRadius: 6, fontSize: 13,
                        border: `1px solid ${C.gray200}`, marginTop: 4, fontFamily: "monospace", boxSizing: "border-box",
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── Resource Estimate ── */}
          <div style={{
            marginTop: 24, padding: "12px 16px", borderRadius: 8,
            background: `linear-gradient(135deg, ${C.teal}08, ${C.accent}08)`,
            border: `1px solid ${C.accent}30`,
            display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13,
          }}>
            <div style={{ color: C.gray500 }}>
              <strong style={{ color: C.gray700 }}>Estimated Resources:</strong>{" "}
              {selectedTool.id === "esmfold" ? "8 CPU · 32 GB · GPU optional · ~15 min" :
               selectedTool.id === "auto" ? "Depends on auto-selected tool" :
               `8 CPU · 64 GB · A100/H100/H200 GPU · ~${selectedTool.id === "boltz" ? "2h" : selectedTool.id === "chai" ? "1.5h" : "3h"}`
              }
            </div>
            <Badge color="blue">gpu2 partition</Badge>
          </div>

          {/* ── Output Folder ── */}
          <div style={{ marginTop: 20 }}>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: C.gray500, marginBottom: 4 }}>
              Output Folder
            </label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                type="text" defaultValue="/user@bvbrc/home/StructurePrediction/crambin_2026-03-05"
                style={{
                  flex: 1, padding: "8px 12px", borderRadius: 8, fontSize: 13,
                  border: `1px solid ${C.gray200}`, fontFamily: "monospace", outline: "none",
                }}
              />
              <button style={{
                padding: "8px 14px", borderRadius: 8, border: "none",
                background: C.gray100, color: C.gray500, fontSize: 13, cursor: "pointer",
              }}>Browse</button>
            </div>
          </div>

          {/* ── Submit ── */}
          <div style={{ marginTop: 28, display: "flex", gap: 12, justifyContent: "flex-end" }}>
            <button style={{
              padding: "10px 24px", borderRadius: 8, border: `1px solid ${C.gray200}`,
              background: C.white, color: C.gray500, fontSize: 14, cursor: "pointer",
            }}>Reset</button>
            <button
              onClick={onSubmit}
              style={{
                padding: "10px 32px", borderRadius: 8, border: "none",
                background: `linear-gradient(135deg, ${C.teal}, ${C.accent})`,
                color: C.white, fontSize: 14, fontWeight: 600, cursor: "pointer",
                boxShadow: `0 4px 12px ${C.accent}40`,
              }}
            >Submit Job</button>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ─── Results Dashboard ───────────────────────────────────────────

function ResultsDashboard({ onBack }) {
  const r = MOCK_RESULTS;
  const [activeTab, setActiveTab] = useState("overview");

  const plddtColor = (v) => v >= 90 ? C.green : v >= 70 ? C.accent : v >= 50 ? C.amber : C.red;
  const plddtLabel = (v) => v >= 90 ? "Very High" : v >= 70 ? "High" : v >= 50 ? "Low" : "Very Low";

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      {/* Header */}
      <div style={{
        background: `linear-gradient(135deg, ${C.navy} 0%, ${C.teal} 100%)`,
        borderRadius: 16, padding: "24px 32px", marginBottom: 20,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <button onClick={onBack} style={{
                background: "rgba(255,255,255,0.15)", border: "none", borderRadius: 6,
                color: C.white, padding: "4px 10px", cursor: "pointer", fontSize: 12,
              }}>← Back</button>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: C.white }}>
                Job {r.jobId}
              </h1>
              <Badge color="green">Completed</Badge>
            </div>
            <p style={{ margin: 0, fontSize: 13, color: C.accentLight }}>
              {r.inputFile} · {r.sequenceLength} residues · {r.tool} · {r.numSamples} samples
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: C.accentLight }}>Runtime</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{r.runtime}</div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {[["overview", "Overview"], ["confidence", "Confidence"], ["comparison", "Tool Comparison"], ["files", "Output Files"]].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              fontSize: 13, fontWeight: 500, transition: "all 0.15s",
              background: activeTab === id ? C.accent : C.gray100,
              color: activeTab === id ? C.white : C.gray500,
            }}
          >{label}</button>
        ))}
      </div>

      {/* ── Overview Tab ── */}
      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Score Cards */}
          <Card style={{ padding: 24 }}>
            <SectionHeader title="Quality Scores" />
            <div style={{ display: "flex", justifyContent: "space-around", marginTop: 8 }}>
              <StatBox label="Mean pLDDT" value={r.plddt_mean.toFixed(1)} sub={plddtLabel(r.plddt_mean)} color={plddtColor(r.plddt_mean)} />
              <div style={{ width: 1, background: C.gray200 }} />
              <StatBox label="pTM Score" value={r.ptm.toFixed(2)} sub={r.ptm >= 0.8 ? "High confidence" : "Moderate"} color={r.ptm >= 0.8 ? C.green : C.amber} />
              <div style={{ width: 1, background: C.gray200 }} />
              <StatBox label="Samples" value={r.numSamples} sub="generated" color={C.gray700} />
            </div>
          </Card>

          {/* Model Ranking */}
          <Card style={{ padding: 24 }}>
            <SectionHeader title="Model Ranking" />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {r.models.map(m => (
                <div key={m.rank} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "6px 10px",
                  borderRadius: 6, background: m.rank === 1 ? `${C.accent}08` : "transparent",
                  border: m.rank === 1 ? `1px solid ${C.accent}30` : "1px solid transparent",
                }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 700,
                    background: m.rank === 1 ? C.accent : C.gray200,
                    color: m.rank === 1 ? C.white : C.gray500,
                  }}>{m.rank}</div>
                  <div style={{ flex: 1, fontSize: 13, fontFamily: "monospace", color: C.gray700 }}>{m.file}</div>
                  <Badge color={m.plddt >= 90 ? "green" : m.plddt >= 80 ? "blue" : "amber"}>
                    pLDDT {m.plddt}
                  </Badge>
                  <span style={{ fontSize: 12, color: C.gray400, width: 60, textAlign: "right" }}>
                    pTM {m.ptm}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Per-residue chart */}
          <Card style={{ padding: 24, gridColumn: "1 / -1" }}>
            <SectionHeader title="Per-Residue pLDDT (Best Model)" subtitle="Colored by confidence: green ≥90, cyan ≥70, amber ≥50, red <50" />
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={r.perResidue} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.gray200} />
                <XAxis
                  dataKey="residue" tick={{ fontSize: 10, fill: C.gray400 }}
                  interval={4} axisLine={{ stroke: C.gray200 }}
                />
                <YAxis
                  domain={[0, 100]} tick={{ fontSize: 10, fill: C.gray400 }}
                  axisLine={{ stroke: C.gray200 }}
                />
                <Tooltip
                  formatter={(v, n, p) => [`${v.toFixed(1)}`, "pLDDT"]}
                  labelFormatter={(i) => `Residue ${i} (${r.perResidue[i-1]?.name || ""})`}
                  contentStyle={{ borderRadius: 8, border: `1px solid ${C.gray200}`, fontSize: 12 }}
                />
                <Bar dataKey="plddt" radius={[2, 2, 0, 0]}>
                  {r.perResidue.map((entry, i) => (
                    <rect key={i} fill={plddtColor(entry.plddt)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            {/* Legend */}
            <div style={{ display: "flex", gap: 16, justifyContent: "center", marginTop: 8 }}>
              {[["Very High (≥90)", C.green], ["High (70-90)", C.accent], ["Low (50-70)", C.amber], ["Very Low (<50)", C.red]].map(([label, color]) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: C.gray500 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
                  {label}
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ── Confidence Tab ── */}
      {activeTab === "confidence" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card style={{ padding: 24, gridColumn: "1 / -1" }}>
            <SectionHeader title="Confidence Distribution" subtitle="Histogram of per-residue pLDDT values" />
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={[
                { range: "0-50", count: r.perResidue.filter(x => x.plddt < 50).length, fill: C.red },
                { range: "50-70", count: r.perResidue.filter(x => x.plddt >= 50 && x.plddt < 70).length, fill: C.amber },
                { range: "70-90", count: r.perResidue.filter(x => x.plddt >= 70 && x.plddt < 90).length, fill: C.accent },
                { range: "90-100", count: r.perResidue.filter(x => x.plddt >= 90).length, fill: C.green },
              ]} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.gray200} />
                <XAxis dataKey="range" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} label={{ value: "Residues", angle: -90, position: "insideLeft", fontSize: 12, fill: C.gray400 }} />
                <Tooltip contentStyle={{ borderRadius: 8, border: `1px solid ${C.gray200}`, fontSize: 12 }} />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {[C.red, C.amber, C.accent, C.green].map((color, i) => (
                    <rect key={i} fill={color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <Card style={{ padding: 24 }}>
            <SectionHeader title="Model pLDDT Comparison" />
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={r.models.map(m => ({ ...m, name: `Model ${m.rank}` }))} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.gray200} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[75, 100]} tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="plddt" stroke={C.accent} strokeWidth={2} dot={{ r: 5, fill: C.accent }} name="pLDDT" />
                <Line type="monotone" dataKey="ptm" stroke={C.purple} strokeWidth={2} dot={{ r: 5, fill: C.purple }} name="pTM (×100)" />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          <Card style={{ padding: 24 }}>
            <SectionHeader title="Summary Statistics" />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
              {[
                ["Residues ≥90", r.perResidue.filter(x => x.plddt >= 90).length, `of ${r.sequenceLength}`, C.green],
                ["Residues ≥70", r.perResidue.filter(x => x.plddt >= 70).length, `of ${r.sequenceLength}`, C.accent],
                ["Min pLDDT", Math.min(...r.perResidue.map(x => x.plddt)).toFixed(1), "lowest residue", C.amber],
                ["Max pLDDT", Math.max(...r.perResidue.map(x => x.plddt)).toFixed(1), "highest residue", C.green],
              ].map(([label, value, sub, color]) => (
                <div key={label} style={{ padding: 12, borderRadius: 8, background: C.gray100, textAlign: "center" }}>
                  <StatBox label={label} value={value} sub={sub} color={color} />
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ── Tool Comparison Tab ── */}
      {activeTab === "comparison" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card style={{ padding: 24 }}>
            <SectionHeader title="Tool Capabilities Radar" />
            <ResponsiveContainer width="100%" height={280}>
              <RadarChart data={r.radarData}>
                <PolarGrid stroke={C.gray200} />
                <PolarAngleAxis dataKey="metric" tick={{ fontSize: 11, fill: C.gray500 }} />
                <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 9 }} />
                <Radar name="Boltz-2" dataKey="Boltz" stroke={C.accent} fill={C.accent} fillOpacity={0.15} strokeWidth={2} />
                <Radar name="Chai-1" dataKey="Chai" stroke={C.purple} fill={C.purple} fillOpacity={0.1} strokeWidth={2} />
                <Radar name="AlphaFold 2" dataKey="AlphaFold" stroke={C.green} fill={C.green} fillOpacity={0.1} strokeWidth={2} />
                <Radar name="ESMFold" dataKey="ESMFold" stroke={C.amber} fill={C.amber} fillOpacity={0.1} strokeWidth={2} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </RadarChart>
            </ResponsiveContainer>
          </Card>

          <Card style={{ padding: 24 }}>
            <SectionHeader title="Quality vs Runtime" subtitle="pLDDT score relative to computation time" />
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={r.toolComparison} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.gray200} />
                <XAxis dataKey="tool" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="left" domain={[70, 100]} tick={{ fontSize: 10 }} label={{ value: "pLDDT", angle: -90, position: "insideLeft", fontSize: 11 }} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} label={{ value: "Runtime (min)", angle: 90, position: "insideRight", fontSize: 11 }} />
                <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="left" dataKey="plddt" fill={C.accent} radius={[4, 4, 0, 0]} name="pLDDT" />
                <Bar yAxisId="right" dataKey="runtime" fill={C.gray300} radius={[4, 4, 0, 0]} name="Runtime (min)" />
              </BarChart>
            </ResponsiveContainer>
          </Card>

          {/* Comparison table */}
          <Card style={{ padding: 24, gridColumn: "1 / -1" }}>
            <SectionHeader title="Tool Comparison Table" subtitle="Side-by-side results for this input (crambin, 46 residues)" />
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${C.gray200}` }}>
                    {["Tool", "pLDDT", "pTM", "Runtime", "MSA Required", "GPU Required", "Best For"].map(h => (
                      <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 600, color: C.gray400, textTransform: "uppercase" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Boltz-2", "92.4", "0.89", "1h 23m", "Optional", "Yes", "Ligands, DNA/RNA, complexes"],
                    ["Chai-1", "90.1", "0.86", "1h 07m", "Optional", "Yes", "Fast multimers"],
                    ["AlphaFold 2", "94.2", "0.91", "4h 00m", "Yes", "Yes", "Highest accuracy, gold standard"],
                    ["ESMFold", "85.3", "0.74", "12m", "No", "Optional", "Quick screening, large batches"],
                  ].map((row, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${C.gray100}` }}>
                      {row.map((cell, j) => (
                        <td key={j} style={{
                          padding: "10px 12px", color: C.gray700,
                          fontWeight: j === 0 ? 600 : 400,
                        }}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {/* ── Files Tab ── */}
      {activeTab === "files" && (
        <Card style={{ padding: 24 }}>
          <SectionHeader title="Output Files" subtitle={`/user@bvbrc/home/StructurePrediction/crambin_2026-03-05/`} />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {[
              ["📄", "model_1.pdb", "Structure", "245 KB", C.green],
              ["📄", "model_1.cif", "Structure", "312 KB", C.green],
              ["📄", "model_2.pdb", "Structure", "245 KB", C.blue],
              ["📄", "model_2.cif", "Structure", "311 KB", C.blue],
              ["📄", "model_3.pdb", "Structure", "244 KB", C.blue],
              ["📊", "confidence_scores.json", "JSON", "18 KB", C.purple],
              ["📊", "per_residue_plddt.json", "JSON", "4 KB", C.purple],
              ["📋", "metadata.json", "JSON", "2 KB", C.gray500],
              ["📋", "run_log.txt", "Log", "34 KB", C.gray500],
              ["📦", "all_results.tar.gz", "Archive", "1.2 MB", C.amber],
            ].map(([icon, name, type, size, color], i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                borderRadius: 8, background: i % 2 === 0 ? C.gray100 : "transparent",
              }}>
                <span style={{ fontSize: 18 }}>{icon}</span>
                <span style={{ flex: 1, fontSize: 13, fontFamily: "monospace", color: C.gray700, fontWeight: 500 }}>{name}</span>
                <Badge color={type === "Structure" ? "green" : type === "JSON" ? "purple" : "gray"}>{type}</Badge>
                <span style={{ fontSize: 12, color: C.gray400, width: 60, textAlign: "right" }}>{size}</span>
                <button style={{
                  padding: "4px 12px", borderRadius: 6, border: `1px solid ${C.gray200}`,
                  background: C.white, color: C.accent, fontSize: 11, fontWeight: 600, cursor: "pointer",
                }}>Download</button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────

export default function App() {
  const [view, setView] = useState("form");

  return (
    <div style={{
      minHeight: "100vh", background: C.offWhite,
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      padding: "32px 24px",
    }}>
      {view === "form" ? (
        <SubmissionForm onSubmit={() => setView("results")} />
      ) : (
        <ResultsDashboard onBack={() => setView("form")} />
      )}
    </div>
  );
}
