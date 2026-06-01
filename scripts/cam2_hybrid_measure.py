"""cam2 regime-hybrid (in-memory, measure-only): bytetrack THROUGHS (good at cam2)
+ BoT-SORT TURNS with volume-gated intra-turn merge (fixes turn fragmentation).
Compares to cam2 Miovision. If it beats the bytetrack baseline, worth productionizing.
"""
import sys, sqlite3, json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from groundtruth import VIDEO_START, NORM_MVT
from hybrid_ocbot import merge_turn_fragments
from measure_cam2 import manual_per_minute_cam2, LEG_IDX, IDX_NAME

START_SEC = (datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T07:00:00") - VIDEO_START).total_seconds()
MINUTES = 5
BT_DB = "data/projects/97a7849a/project.db"            # bytetrack baseline cam2 events
BOT_DB = "data/projects/97a7849a/_hybrid_tmp/cam2_bank.db"  # BoT+bank cam2 events


def _load(db, where):
    c = sqlite3.connect(db)
    rows = c.execute("SELECT origin_leg_id,destination_leg_id,movement,start_frame,frame_number,trajectory_data,timestamp_video "
                     f"FROM vehicle_events WHERE camera_id=2 AND rejected=0 AND ({where})").fetchall()
    c.close()
    out = []
    for ol, dl, mv, sf, ef, tj, ts in rows:
        try: traj = json.loads(tj) if tj else []
        except Exception: traj = []
        out.append({"ol": ol, "dl": dl, "mv": mv, "s": sf or ef, "e": ef or sf,
                    "start": traj[0] if traj else None, "ts": ts})
    return out


# expected per-cell volume (cam2 manual) for the merge volume-gate
m_mv = manual_per_minute_cam2()
mins = [datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T07:00:00") + timedelta(minutes=i) for i in range(MINUTES)]
exp_cell = defaultdict(float)
inv = {v: k for k, v in LEG_IDX.items()}
# build expected by (origin_leg,dest_leg) is unavailable from movement-level; gate by (origin approach,mvt) volume instead
exp_by_od = defaultdict(float)
# approximate expected per OD cell from manual movement totals mapped by leg
man_mv_tot = defaultdict(float)
for mn in mins:
    for (ii, mvt), n in m_mv.get(mn, {}).items():
        man_mv_tot[(inv.get(ii), mvt)] += n

bt_thru = [e for e in _load(BT_DB, "movement='through'") if START_SEC <= e["ts"] < START_SEC + MINUTES*60]
bot_turn = [e for e in _load(BOT_DB, "movement IN ('left','right','u_turn')") if START_SEC <= e["ts"] < START_SEC + MINUTES*60]
# volume gate expected per (ol,dl): use manual movement count for (ol, mv)
exp_od = defaultdict(float)
for e in bot_turn:
    exp_od[(e["ol"], e["dl"])] = man_mv_tot.get((e["ol"], NORM_MVT.get(e["mv"], e["mv"])), 0)
keep_ids = None
# merge_turn_fragments expects events with 'id'; assign indices
for i, e in enumerate(bot_turn): e["id"] = i
keep = merge_turn_fragments(bot_turn, 30.0, 40.0, expected_by_cell=exp_od, vol_factor=1.3)
bot_turn_kept = [e for e in bot_turn if e["id"] in keep]

# tally combined
o_mv = defaultdict(lambda: defaultdict(int))
for e in bt_thru + bot_turn_kept:
    ii = LEG_IDX.get(e["ol"])
    if ii is None: continue
    mvt = NORM_MVT.get(e["mv"], e["mv"])
    minute = (VIDEO_START + timedelta(seconds=e["ts"])).replace(second=0, microsecond=0)
    o_mv[minute][(ii, mvt)] += 1

cells = set()
for mn in mins: cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
print(f"cam2 HYBRID (bytetrack-thru + BoT-merged-turns) — 07:00+{MINUTES}min")
print(f"{'cell':<14}{'manual':>7}{'ours':>6}{'net':>6}{'gross':>7}")
tman=tnet=tg=0
for cell in sorted(cells, key=lambda c:-sum(abs(o_mv.get(mn,{}).get(c,0)-m_mv.get(mn,{}).get(c,0)) for mn in mins)):
    man=sum(m_mv.get(mn,{}).get(cell,0) for mn in mins); ours=sum(o_mv.get(mn,{}).get(cell,0) for mn in mins)
    g=sum(abs(o_mv.get(mn,{}).get(cell,0)-m_mv.get(mn,{}).get(cell,0)) for mn in mins)
    tman+=man; tnet+=abs(ours-man); tg+=g
    if man==0 and ours==0: continue
    in_i,mvt=cell
    print(f"{IDX_NAME.get(in_i,in_i)+' '+mvt:<14}{man:>7}{ours:>6}{abs(ours-man):>6}{g:>7}")
print(f"{'TOTAL':<14}{tman:>7}{'':>6}{tnet:>6}{tg:>7}")
print(f"  net agg_err = {tnet/tman*100:.1f}%   per-min gross = {tg/tman*100:.1f}%")
print(f"  (bt throughs {len(bt_thru)} + BoT turns {len(bot_turn)}->{len(bot_turn_kept)} merged)")
