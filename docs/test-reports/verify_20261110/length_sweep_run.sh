#!/bin/bash
SP=$(cat /tmp/claude-3581/sp.txt); W=/home/wilke/Development/PredictStructureApp/.worktree/verify-main
S=/scout/containers/folding_prod.sif; OUT=$SP/sweep; RES=$OUT/results.tsv
echo -e "tool\tlen\trc\tseconds\tpeak_mib\tnote" > $RES
python3 - <<PY
import random; random.seed(7); aa="ACDEFGHIKLMNPQRSTVWY"
for n in (1000,1500,1600,2000,2500,3000,3200,3500,4000):
    open("$OUT/seq%d.fasta"%n,"w").write(">p\n"+"".join(random.choice(aa) for _ in range(n))+"\n")
PY
extra() { case $1 in openfold) echo "--no-msa-server --no-templates";; esac; }
run() { t=$1; n=$2; force=$3; d=$OUT/${t}_${n}_$force; rm -rf $d
  s=$(date +%s); peak=0
  ( while true; do m=$(nvidia-smi -i 7 --query-gpu=memory.used --format=csv,noheader,nounits); echo $m >> $d.mem; sleep 5; done ) & mp=$!
  CUDA_VISIBLE_DEVICES=7 timeout 2700 apptainer exec --nv --bind /home/wilke:/home/wilke --bind /local_databases:/local_databases $S /bin/bash -lc "cd $W && PYTHONPATH=. /opt/conda-predict/bin/python -m predict_structure.cli $t --protein $OUT/seq$n.fasta -o $d $force $(extra $t)" > $d.log 2>&1; rc=$?
  kill $mp 2>/dev/null; peak=$(sort -n $d.mem 2>/dev/null | tail -1)
  note=$(grep -m1 -iE "out of memory|OutOfMemory|exceeds|residues" $d.log | cut -c1-120)
  echo -e "$t\t$n\t$rc\t$(( $(date +%s)-s ))\t$peak\t$note" >> $RES; }
# cap messaging, cheap
run boltz 3200 ""; run esmfold 1600 ""
for n in 1500 2000 3000 4000; do run esmfold $n --force; done
for n in 1500 2000 2500 3000; do run esmfold2 $n --force; done
for n in 2500 3000 3500 4000; do run boltz $n --force; done
for n in 2500 3000 3500 4000; do run openfold $n --force; done
echo DONE >> $RES
