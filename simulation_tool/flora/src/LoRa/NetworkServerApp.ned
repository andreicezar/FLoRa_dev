//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Lesser General Public License for more details.
// 
// You should have received a copy of the GNU Lesser General Public License
// along with this program.  If not, see http://www.gnu.org/licenses/.
// 

package flora.LoRa;
import inet.applications.contract.IApp;

//
// LoRa Network Server Application with Advanced ADR Optimization Features
//
// This module implements a LoRa network server with support for multiple
// ADR optimization techniques including weighted SNR processing, dynamic
// window sizing, energy bias, and congestion-aware load balancing.
//
simple NetworkServerApp like IApp
{
    parameters:
        // ===================================================================
        // 1. SIMULATION SIGNALS AND STATISTICS
        // ===================================================================
        @signal[LoRa_ServerPacketReceived](type=bool); // Packet reception signal
        @statistic[LoRa_ServerPacketReceived](source=LoRa_ServerPacketReceived; record=count);

        // ===================================================================
        // 2. BASIC NETWORK CONFIGURATION
        // ===================================================================
        int localPort = default(-1);                   // Local UDP port (-1: use ephemeral port)
        string localAddress = default("");             // Local IP address (empty: any interface)
        int destPort = default(-1);                    // Destination port for communication
        bool evaluateADRinServer = default(false);     // Enable server-side ADR evaluation
        int headerLength @unit(B) = default(8B);       // LoRa header length in bytes

        // ===================================================================
        // 3. BASIC ADR ALGORITHM CONFIGURATION
        // ===================================================================
        string adrMethod = default("max");             // ADR algorithm: "max", "ADRopt", etc.
        double adrDeviceMargin = default(15);          // SNR margin for ADR decisions (dB)

        // ===================================================================
        // 4. DEBUG AND LOGGING SETTINGS
        // ===================================================================
        bool debugADR = default(false);                // Enable/disable ADR debug logging
        string debugLogFileName = default("debug_adr_log.txt"); // Debug log file name (supports OMNeT++ variables)

        // ===================================================================
        // 5. WEIGHTED SNR PROCESSING OPTIMIZATION
        // ===================================================================
        bool useWeightedSNR = default(true);           // Enable weighted SNR instead of raw max SNR
        double weightingAlpha = default(0.7);          // Base smoothing factor for SNR averaging
        double stableAlpha = default(0.6);             // Alpha for stable channel conditions
        double unstableAlpha = default(0.85);          // Alpha for unstable channel conditions  
        bool useAdaptiveAlpha = default(true);         // Enable adaptive alpha based on channel variance
        double gwTimeoutSeconds = default(300);        // Gateway timeout for cleaning stale entries (seconds)

        // ===================================================================
        // 6. DYNAMIC WINDOW SIZE ADAPTATION
        // ===================================================================
        bool useDynamicWindow = default(true);         // Enable dynamic ADR window sizing
        int baseWindowSize = default(20);              // Default window size (packets)
        int minWindowSize = default(5);                // Minimum window size for unstable conditions
        int maxWindowSize = default(40);               // Maximum window size for stable conditions
        double stableVarianceThreshold = default(1.0); // SNR variance threshold for stable conditions (dB²)
        double unstableVarianceThreshold = default(3.0); // SNR variance threshold for unstable conditions (dB²)

        // ===================================================================
        // 7. ENERGY BIAS FOR ROBUSTNESS
        // ===================================================================
        bool useWeightBias = default(false);           // Enable energy bias penalty for lower SFs
        double weightRobustnessBias = default(0.1);    // Bias factor: penalty per SF step below SF12

        // ===================================================================
        // 8. CONGESTION-AWARE NETWORK OPTIMIZATION
        // ===================================================================
        bool useCongestionAwareness = default(true);   // Enable network-wide congestion management
        double maxSFLoad = default(0.3);               // Maximum fraction of nodes per SF (0.0-1.0)
        double collisionThreshold = default(0.5);      // Collision rate threshold triggering SF rebalancing
        double snrStabilityThreshold = default(2.0);   // SNR variance threshold for stable nodes (dB)
        double sfChangeDebounce @unit(s) = default(300s); // Minimum time between SF changes per node

    gates:
        // ===================================================================
        // 9. COMMUNICATION GATES
        // ===================================================================
        output socketOut @labels(UdpControlInfo/up);   // UDP socket output
        input socketIn @labels(UdpControlInfo/down);    // UDP socket input
}

//
// Parameter Usage Guide:
//
// Basic Usage (Standard ADR):
//   *.networkServer.app[0].useWeightedSNR = false
//   *.networkServer.app[0].useDynamicWindow = false  
//   *.networkServer.app[0].useWeightBias = false
//   *.networkServer.app[0].useCongestionAwareness = false
//
// Full Optimization (All Features):
//   *.networkServer.app[0].useWeightedSNR = true
//   *.networkServer.app[0].useDynamicWindow = true
//   *.networkServer.app[0].useWeightBias = true
//   *.networkServer.app[0].useCongestionAwareness = true
//
// Debug Logging:
//   *.networkServer.app[0].debugADR = true
//   *.networkServer.app[0].debugLogFileName = "debug_adr_${inifile}_${datetime}.txt"
//