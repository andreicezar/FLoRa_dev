@echo off
REM Windows Batch File to Run FLoRa Simulations
REM Save this as run_flora_simulation.bat

echo Starting FLoRa SF-Only Simulation...
echo.

REM Launch OMNeT++ environment and run simulation
"C:\omnetpp-6.1.0\omnetpp-6.1\mingwenv.cmd" -c "export PATH='/d/Doctorat/anul_2/apps/FLoRa_development/flora/src:/d/Doctorat/anul_2/apps/FLoRa_development/inet4.4/src:$PATH' && cd /d/Doctorat/anul_2/apps/FLoRa_development/flora/simulations/examples && opp_run -u Cmdenv -c General -f omnetpp-02_sf_only.ini -n .:..:../../src:../../../inet4.4/src -l ../../src/flora -l ../../../inet4.4/src/INET"

echo.
echo Simulation completed.
pause