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

#ifndef __LORANETWORK_NETWORKSERVERAPP_H_
#define __LORANETWORK_NETWORKSERVERAPP_H_

#include <omnetpp.h>
#include "inet/physicallayer/wireless/common/contract/packetlevel/RadioControlInfo_m.h"
#include <vector>
#include <tuple>
#include <algorithm>
#include "inet/common/INETDefs.h"

#include "LoRaMacControlInfo_m.h"
#include "LoRaMacFrame_m.h"
#include "inet/applications/base/ApplicationBase.h"
#include "inet/transportlayer/contract/udp/UdpSocket.h"
#include "../LoRaApp/LoRaAppPacket_m.h"
#include <list>

namespace flora {

class knownNode
{
public:
    MacAddress srcAddr;
    int framesFromLastADRCommand = 0;
    int lastSeqNoProcessed = 0;
    int firstSeqNoProcessed = 0;
    int numberOfSentADRPackets = 0;
    int currentNbTrans = 1;  // <-- ADD THIS: Track current NbTrans setting
    std::list<double> adrListSNIR;
    cOutVector *historyAllSNIR = nullptr;
    cOutVector *historyAllRSSI = nullptr;
    cOutVector *receivedSeqNumber = nullptr;
    cOutVector *calculatedSNRmargin = nullptr;
    std::map<L3Address, std::list<double>> gwAdrListSNIR;
    std::map<L3Address, cOutVector*> gwHistorySNIR;
    std::list<int> seqNumWindow; // size capped at 20
  
    // NEW - ADD THESE 3 LINES:
    std::map<L3Address, double> gwWeightedSNIR;
    std::map<L3Address, bool> gwWeightedInitialized;
    std::map<L3Address, simtime_t> gwLastUpdate;
    int currentNodeWideWindowSize = 20;  // Track current window size for this node
    static const int WINDOW_DEBOUNCE_THRESHOLD = 3;  // Must be stable for 3 evaluations
    // Debounce pentru dynamic window
    int lastDynamicWindowSize = 20;
    int windowSizeStableCount = 0;
};

class knownGW
{
public:
    L3Address ipAddr;
};

class receivedPacket
{
public:
    Packet* rcvdPacket = nullptr;
    cMessage* endOfWaiting = nullptr;
    std::vector<std::tuple<L3Address, double, double>> possibleGateways; // <address, sinr, rssi>
};

class NetworkServerApp : public cSimpleModule, cListener
{
  private:
    bool debugADR;
    std::string debugLogFileName;  // ADD THIS LI
    // NEW - ADD THESE 6 LINES:
    double weightingAlpha = 0.7;
    bool useWeightedSNR = true;
    double stableAlpha = 0.6;
    double unstableAlpha = 0.85;
    bool useAdaptiveAlpha = true;
    simtime_t gwTimeoutSeconds = 300;

    // NEW: Dynamic Window Parameters
    bool useDynamicWindow = true;
    int baseWindowSize = 20;         // Default window size
    int minWindowSize = 5;           // Minimum window size (unstable conditions)
    int maxWindowSize = 40;          // Maximum window size (stable conditions)
    double stableVarianceThreshold = 1.0;    // Below this = stable (larger window)
    double unstableVarianceThreshold = 3.0;  // Above this = unstable (smaller window)
    // NEW: Weight bias parameters
    bool useWeightBias = false;
    double weightRobustnessBias = 0.1;

      // ADD: Congestion tracking
    std::map<int, int> sfUsageCount;  // SF -> number of nodes using it
    std::map<int, double> sfCollisionRate;  // SF -> estimated collision rate
    std::map<MacAddress, int> nodeCurrentSF;  // Track current SF per node
    std::map<MacAddress, simtime_t> lastSFChange;  // Anti-flapping
    
    // Congestion-aware parameters
    bool useCongestionAwareness = true;
    double maxSFLoad = 0.3;  // Max 30% nodes per SF
    double collisionThreshold = 0.5;  // 50% collision rate triggers change
    double snrStabilityThreshold = 2.0;  // SNR variance for stable channel
    simtime_t sfChangeDebounce = 300;  // 5 minutes between SF changes

  protected:
    std::vector<knownNode> knownNodes;
    std::vector<knownGW> knownGateways;
    std::vector<receivedPacket> receivedPackets;
    int localPort = -1, destPort = -1;
    std::vector<std::tuple<MacAddress, int>> recvdPackets;
    // state
    UdpSocket socket;
    cMessage *selfMsg = nullptr;
    int totalReceivedPackets;
    std::string adrMethod;
    double adrDeviceMargin;
    std::map<int, int> numReceivedPerNode;

  protected:
    virtual void initialize(int stage) override;
    virtual void handleMessage(cMessage *msg) override;
    virtual void finish() override;
    void processLoraMACPacket(Packet *pk);
    void startUDP();
    void setSocketOptions();
    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    bool isPacketProcessed(const Ptr<const LoRaMacFrame> &);
    void updateKnownNodes(Packet* pkt);
    void addPktToProcessingTable(Packet* pkt);
    void processScheduledPacket(cMessage* selfMsg);
    void evaluateADR(Packet *pkt, L3Address pickedGateway, double SNIRinGW, double RSSIinGW);
    void receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details) override;
    bool evaluateADRinServer;

    cHistogram receivedRSSI;
    
    double calculateCurrentPER(const knownNode& node);
    double estimateSNR_d(const knownNode& node, int seqNo);
    double calculateFER(int SF, double SNR_d);
    std::tuple<int, int, int> chooseBestConfiguration(const std::map<std::tuple<int, int, int>, double>& PERpredic, double PERtarget, int payloadSize);
    double calculateTimeOnAir(int SF, int payloadBytes);
    double estimateGWSNR_d(const knownNode& node, const L3Address& gwAddress, double currentSNIR, double sizeS);

    // NEW - ADD THESE 4 LINES:
    void updateWeightedSNR(knownNode& node, const L3Address& gwAddress, double currentSNIR);
    double getAdaptiveAlpha(const knownNode& node, const L3Address& gwAddress);
    void cleanupStaleGateways(knownNode& node);
    double getWeightedSNRForGateway(const knownNode& node, const L3Address& gwAddress);

    // Dynamic window calculation function
    int calculateDynamicWindowSize(const knownNode& node, const L3Address& gwAddress);
    
    // ADD: New congestion methods
    void updateSFUsageStats();
    double calculateSFCollisionRate(int SF);
    bool isChannelCongested(int SF);
    bool isNodeSNRStable(const knownNode& node);
    int selectLeastCongestedSF(const knownNode& node, double targetPER);
    void distributeSFsAcrossNetwork();
    std::tuple<int, int, int> congestionAwareConfiguration(
        const knownNode& node, 
        const std::map<std::tuple<int, int, int>, double>& PERpredic,
        double PERtarget,
        int payloadSize);
  public:
    simsignal_t LoRa_ServerPacketReceived;
    int counterOfSentPacketsFromNodes = 0;
    int counterOfSentPacketsFromNodesPerSF[6];
    int counterUniqueReceivedPackets = 0;
    int counterUniqueReceivedPacketsPerSF[6];
};
} //namespace inet
#endif