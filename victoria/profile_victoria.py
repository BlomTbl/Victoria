"""
Profiler script for Victoria — run this alongside the network in the DTD environment.
Writes cProfile output to profile_output.txt and a sorted summary.

Usage:
  python profile_victoria.py victest2.inp
"""
import cProfile
import pstats
import io
import sys
import time

INP = sys.argv[1] if len(sys.argv) > 1 else 'victest2.inp'
N_STEPS = 20   # Profile on the first 20 steps (representative)

def run_profile(inp_file, n_steps):
    import epynet
    import phreeqpython
    from victoria import Victoria

    net = epynet.Network(inp_file)
    pp  = phreeqpython.PhreeqPython()
    sol_high = pp.add_solution({'units': 'mmol/kgw', 'Ca': 10})
    sol_low  = pp.add_solution({})

    # Autodetect reservoirs
    reservoir_uids = [r.uid for r in net.reservoirs]
    input_sol = {uid: sol_high for uid in reservoir_uids}
    input_sol['_bg'] = sol_low

    net.solve(simtime=0)
    vic = Victoria(net, pp)
    vic.fill_network(input_sol, from_reservoir=True)

    hydstep = 300  # 5 min
    simtime = 0
    for step in range(n_steps):
        net.solve(simtime=simtime)
        vic.check_flow_direction()
        vic.step(timestep=hydstep, input_sol=input_sol)
        simtime += hydstep

    net.close()

pr = cProfile.Profile()
pr.enable()
run_profile(INP, N_STEPS)
pr.disable()

buf = io.StringIO()
ps  = pstats.Stats(pr, stream=buf).sort_stats('cumulative')
ps.print_stats(40)
print(buf.getvalue())

buf2 = io.StringIO()
ps2  = pstats.Stats(pr, stream=buf2).sort_stats('tottime')
ps2.print_stats(30)
print("\n\n=== SORT BY TOTTIME ===")
print(buf2.getvalue())

with open('profile_output.txt', 'w') as f:
    f.write(buf.getvalue())
    f.write('\n\n=== SORT BY TOTTIME ===\n')
    f.write(buf2.getvalue())

print("Written to profile_output.txt")
