import math

def print_gw_positions(N_gw=8, r_gw=1500):
    for i in range(N_gw):
        theta = 2 * math.pi * i / N_gw
        x = r_gw * math.cos(theta)
        y = r_gw * math.sin(theta)
        print(f'**.loRaGW[{i}].mobility.initialX = {x:.2f}m')
        print(f'**.loRaGW[{i}].mobility.initialY = {y:.2f}m\n')

def print_ed_positions(N_ed, r_ed=1000):
    for i in range(N_ed):
        theta = 2 * math.pi * i / N_ed
        x = r_ed * math.cos(theta)
        y = r_ed * math.sin(theta)
        print(f'**.loRaNodes[{i}].mobility.initialX = {x:.2f}m')
        print(f'**.loRaNodes[{i}].mobility.initialY = {y:.2f}m\n')

for n in [10, 20, 40, 60, 80, 100, 120]:
    print(f'\n# GW positions for up to 8 gateways (radius 1500m)')
    print_gw_positions(N_gw=8, r_gw=1500)
    print(f'\n# ED positions for {n} nodes (radius 1000m)')
    print_ed_positions(n)
