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

#include <fstream>
#include "NetworkServerApp.h"
//#include "inet/networklayer/ipv4/IPv4Datagram.h"
//#include "inet/networklayer/contract/ipv4/IPv4ControlInfo.h"
#include "inet/networklayer/common/L3AddressTag_m.h"
#include "inet/transportlayer/common/L4PortTag_m.h"
#include "inet/transportlayer/contract/udp/UdpControlInfo_m.h"
#include "inet/networklayer/common/L3AddressResolver.h"
#include "inet/common/ModuleAccess.h"
#include "inet/applications/base/ApplicationPacket_m.h"

#include "inet/networklayer/common/L3Tools.h"
#include "inet/networklayer/ipv4/Ipv4Header_m.h"
#include <cfloat>
#include <chrono>
#include <iomanip>

#include <fstream>

std::ofstream debugLogFile;

namespace flora {

Define_Module(NetworkServerApp);

void NetworkServerApp::initialize(int stage)
{
    if (stage == 0) {
        debugADR = par("debugADR").boolValue();
        debugLogFileName = par("debugLogFileName").stdstringValue();
        debugLogFile.open(debugLogFileName);
        // DEBUGGING: Force console output to verify code runs
        std::cout << "=== NetworkServerApp::initialize() called ===" << std::endl;
        std::cout << "debugADR = " << debugADR << std::endl;
        
        // NEW - ADD THESE 6 LINES:
        weightingAlpha = par("weightingAlpha").doubleValue();
        useWeightedSNR = par("useWeightedSNR").boolValue();
        stableAlpha = par("stableAlpha").doubleValue();
        unstableAlpha = par("unstableAlpha").doubleValue();
        useAdaptiveAlpha = par("useAdaptiveAlpha").boolValue();
        gwTimeoutSeconds = par("gwTimeoutSeconds").doubleValue();
        
        std::cout << "useWeightedSNR = " << useWeightedSNR << std::endl;
        std::cout << "weightingAlpha = " << weightingAlpha << std::endl;

        useCongestionAwareness = par("useCongestionAwareness").boolValue();
        maxSFLoad = par("maxSFLoad").doubleValue();
        collisionThreshold = par("collisionThreshold").doubleValue();
        snrStabilityThreshold = par("snrStabilityThreshold").doubleValue();
        sfChangeDebounce = par("sfChangeDebounce").doubleValue();
        // Initialize SF usage tracking
        for (int sf = 7; sf <= 12; sf++) {
            sfUsageCount[sf] = 0;
            sfCollisionRate[sf] = 0.0;
        }

        // NEW: Read dynamic window parameters
        useDynamicWindow = par("useDynamicWindow").boolValue();
        baseWindowSize = par("baseWindowSize").intValue();
        minWindowSize = par("minWindowSize").intValue();
        maxWindowSize = par("maxWindowSize").intValue();
        stableVarianceThreshold = par("stableVarianceThreshold").doubleValue();
        unstableVarianceThreshold = par("unstableVarianceThreshold").doubleValue();
        // NEW: Weight bias parameters
        useWeightBias = par("useWeightBias").boolValue();
        weightRobustnessBias = par("weightRobustnessBias").doubleValue();

        std::cout << "useWeightBias = " << useWeightBias << std::endl;
        std::cout << "weightRobustnessBias = " << weightRobustnessBias << std::endl;
        std::cout << "useDynamicWindow = " << useDynamicWindow << std::endl;
        std::cout << "baseWindowSize = " << baseWindowSize << std::endl;
        std::cout << "windowSize range = [" << minWindowSize << ", " << maxWindowSize << "]" << std::endl;
        

        if (debugADR) {
                std::cout << "Creating debug file: " << debugLogFileName << std::endl;
                
                // === Modificare aici ===
                std::string baseName = debugLogFileName;
                auto pos = baseName.find(".ini");
                if (pos != std::string::npos) {
                    baseName = baseName.substr(0, pos);
                }
                auto now = std::chrono::system_clock::now();
                auto time_t = std::chrono::system_clock::to_time_t(now);
                auto tm = *std::localtime(&time_t);
                char timebuf[16];
                std::strftime(timebuf, sizeof(timebuf), "%m_%d_%H", &tm);
                std::string finalName = baseName + "_" + timebuf + ".txt";
                debugLogFile.open(finalName);

                if (debugLogFile.is_open()) {
                    debugLogFile << "ADRopt Debug Log started at " 
                                << std::put_time(&tm, "%m_%d_%H") << std::endl;
                    debugLogFile << "Debug file: " << finalName << std::endl;
                    debugLogFile << "Configuration features:" << std::endl;
                    debugLogFile << "  - Weighted SNR: " << (useWeightedSNR ? "ENABLED" : "DISABLED") << std::endl;
                    debugLogFile << "  - Dynamic window: " << (useDynamicWindow ? "ENABLED" : "DISABLED") << std::endl;
                    debugLogFile << "  - Energy bias: " << (useWeightBias ? "ENABLED" : "DISABLED") << std::endl;
                    debugLogFile << "  - Congestion awareness: " << (useCongestionAwareness ? "ENABLED" : "DISABLED") << std::endl;
                    debugLogFile << std::endl;
                    debugLogFile.flush();
                } else {
                    std::cout << "ERROR: Failed to create debug file!" << std::endl;
                }
        }

        ASSERT(recvdPackets.size()==0);
        LoRa_ServerPacketReceived = registerSignal("LoRa_ServerPacketReceived");
        localPort = par("localPort");
        destPort = par("destPort");
        adrMethod = par("adrMethod").stdstringValue();

    } else if (stage == INITSTAGE_APPLICATION_LAYER) {
        startUDP();
        getSimulation()->getSystemModule()->subscribe("LoRa_AppPacketSent", this);
        evaluateADRinServer = par("evaluateADRinServer");
        adrDeviceMargin = par("adrDeviceMargin");
        receivedRSSI.setName("Received RSSI");
        totalReceivedPackets = 0;
        for(int i=0;i<6;i++)
        {
            counterUniqueReceivedPacketsPerSF[i] = 0;
            counterOfSentPacketsFromNodesPerSF[i] = 0;
        }
    }
}

// ===== NEW: Debug logging macro =====
#define DEBUG_LOG(message) \
    do { \
        if (debugADR && debugLogFile.is_open()) { \
            debugLogFile << message << std::endl; \
        } \
    } while(0)

void NetworkServerApp::startUDP()
{
    socket.setOutputGate(gate("socketOut"));
    const char *localAddress = par("localAddress");
    socket.bind(*localAddress ? L3AddressResolver().resolve(localAddress) : L3Address(), localPort);
}


void NetworkServerApp::handleMessage(cMessage *msg)
{
    if (msg->arrivedOn("socketIn")) {
        auto pkt = check_and_cast<Packet *>(msg);
        const auto &frame  = pkt->peekAtFront<LoRaMacFrame>();
        if (frame == nullptr)
            throw cRuntimeError("Header error type");
        //LoRaMacFrame *frame = check_and_cast<LoRaMacFrame *>(msg);
        if (simTime() >= getSimulation()->getWarmupPeriod())
        {
            totalReceivedPackets++;
        }
        updateKnownNodes(pkt);
        processLoraMACPacket(pkt);
    }
    else if(msg->isSelfMessage()) {
        processScheduledPacket(msg);
    }
}

void NetworkServerApp::processLoraMACPacket(Packet *pk)
{
    const auto & frame = pk->peekAtFront<LoRaMacFrame>();
    if(isPacketProcessed(frame))
    {
        delete pk;
        return;
    }
    addPktToProcessingTable(pk);
}

void NetworkServerApp::finish()
{
    recordScalar("LoRa_NS_DER", double(counterUniqueReceivedPackets)/counterOfSentPacketsFromNodes);
    for(uint i=0;i<knownNodes.size();i++)
    {
        delete knownNodes[i].historyAllSNIR;
        delete knownNodes[i].historyAllRSSI;
        delete knownNodes[i].receivedSeqNumber;
        delete knownNodes[i].calculatedSNRmargin;
        // ADD: Clean up gateway-specific vectors
        for(auto& pair : knownNodes[i].gwHistorySNIR) {
            delete pair.second;
        }
        knownNodes[i].gwHistorySNIR.clear();

        recordScalar("Send ADR for node", knownNodes[i].numberOfSentADRPackets);
    }
    for (std::map<int,int>::iterator it=numReceivedPerNode.begin(); it != numReceivedPerNode.end(); ++it)
    {
        const std::string stringScalar = "numReceivedFromNode " + std::to_string(it->first);
        recordScalar(stringScalar.c_str(), it->second);
    }

    receivedRSSI.recordAs("receivedRSSI");
    recordScalar("totalReceivedPackets", totalReceivedPackets);

    while(!receivedPackets.empty()) {
        receivedPackets.back().endOfWaiting->removeControlInfo();
        delete receivedPackets.back().rcvdPacket;
        if (receivedPackets.back().endOfWaiting && receivedPackets.back().endOfWaiting->isScheduled()) {
            cancelAndDelete(receivedPackets.back().endOfWaiting);
        }
        else
            delete receivedPackets.back().endOfWaiting;
        receivedPackets.pop_back();
    }

    knownNodes.clear();
    receivedPackets.clear();

    recordScalar("counterUniqueReceivedPacketsPerSF SF7", counterUniqueReceivedPacketsPerSF[0]);
    recordScalar("counterUniqueReceivedPacketsPerSF SF8", counterUniqueReceivedPacketsPerSF[1]);
    recordScalar("counterUniqueReceivedPacketsPerSF SF9", counterUniqueReceivedPacketsPerSF[2]);
    recordScalar("counterUniqueReceivedPacketsPerSF SF10", counterUniqueReceivedPacketsPerSF[3]);
    recordScalar("counterUniqueReceivedPacketsPerSF SF11", counterUniqueReceivedPacketsPerSF[4]);
    recordScalar("counterUniqueReceivedPacketsPerSF SF12", counterUniqueReceivedPacketsPerSF[5]);
    if (counterOfSentPacketsFromNodesPerSF[0] > 0)
        recordScalar("DER SF7", double(counterUniqueReceivedPacketsPerSF[0]) / counterOfSentPacketsFromNodesPerSF[0]);
    else
        recordScalar("DER SF7", 0);

    if (counterOfSentPacketsFromNodesPerSF[1] > 0)
        recordScalar("DER SF8", double(counterUniqueReceivedPacketsPerSF[1]) / counterOfSentPacketsFromNodesPerSF[1]);
    else
        recordScalar("DER SF8", 0);

    if (counterOfSentPacketsFromNodesPerSF[2] > 0)
        recordScalar("DER SF9", double(counterUniqueReceivedPacketsPerSF[2]) / counterOfSentPacketsFromNodesPerSF[2]);
    else
        recordScalar("DER SF9", 0);

    if (counterOfSentPacketsFromNodesPerSF[3] > 0)
        recordScalar("DER SF10", double(counterUniqueReceivedPacketsPerSF[3]) / counterOfSentPacketsFromNodesPerSF[3]);
    else
        recordScalar("DER SF10", 0);

    if (counterOfSentPacketsFromNodesPerSF[4] > 0)
        recordScalar("DER SF11", double(counterUniqueReceivedPacketsPerSF[4]) / counterOfSentPacketsFromNodesPerSF[4]);
    else
        recordScalar("DER SF11", 0);

    if (counterOfSentPacketsFromNodesPerSF[5] > 0)
        recordScalar("DER SF12", double(counterUniqueReceivedPacketsPerSF[5]) / counterOfSentPacketsFromNodesPerSF[5]);
    else
        recordScalar("DER SF12", 0);

    // ===== UPDATED: Close debug file only if it was opened =====
    if (debugADR && debugLogFile.is_open()) {
        debugLogFile.close();
    }
}

bool NetworkServerApp::isPacketProcessed(const Ptr<const LoRaMacFrame> &pkt)
{
    for(const auto & elem : knownNodes) {
        if(elem.srcAddr == pkt->getTransmitterAddress()) {
            if(elem.lastSeqNoProcessed > pkt->getSequenceNumber()) return true;
        }
    }
    return false;
}

// Update SF usage statistics
void NetworkServerApp::updateSFUsageStats() {
    // Reset counters
    for (int sf = 7; sf <= 12; sf++) {
        sfUsageCount[sf] = 0;
    }
    
    // Count nodes per SF
    for (const auto& node : knownNodes) {
        if (nodeCurrentSF.count(node.srcAddr)) {
            sfUsageCount[nodeCurrentSF[node.srcAddr]]++;
        }
    }
    
    // Calculate collision rates based on DER
    for (int sf = 7; sf <= 12; sf++) {
        if (counterOfSentPacketsFromNodesPerSF[sf-7] > 0) {
            double der = 1.0 - (double)counterUniqueReceivedPacketsPerSF[sf-7] / 
                              counterOfSentPacketsFromNodesPerSF[sf-7];
            sfCollisionRate[sf] = der;
        }
    }
    
    DEBUG_LOG("\n[CONGESTION] SF Usage Statistics:");
    for (int sf = 7; sf <= 12; sf++) {
        DEBUG_LOG("  SF" << sf << ": " << sfUsageCount[sf] << " nodes, " 
                  << "collision rate: " << sfCollisionRate[sf]);
    }
}

// Check if SF is congested
bool NetworkServerApp::isChannelCongested(int SF) {
    updateSFUsageStats();
    
    int totalNodes = knownNodes.size();
    if (totalNodes == 0) return false;
    
    double sfLoad = (double)sfUsageCount[SF] / totalNodes;
    bool loadCongested = sfLoad > maxSFLoad;
    bool collisionCongested = sfCollisionRate[SF] > collisionThreshold;
    
    DEBUG_LOG("[CONGESTION] SF" << SF << " load: " << sfLoad 
              << " (congested: " << loadCongested << "), "
              << "collision rate: " << sfCollisionRate[SF] 
              << " (congested: " << collisionCongested << ")");
    
    return loadCongested || collisionCongested;
}

// Check if node has stable SNR (not varying due to channel)
bool NetworkServerApp::isNodeSNRStable(const knownNode& node) {
    // Calculate SNR variance across all gateways
    double totalVariance = 0.0;
    int gwCount = 0;
    
    for (const auto& [gwAddr, snrList] : node.gwAdrListSNIR) {
        if (snrList.size() < 5) continue;
        
        double sum = 0.0, sumSquares = 0.0;
        int count = 0;
        
        for (auto it = snrList.rbegin(); it != snrList.rend() && count < 10; ++it, ++count) {
            sum += *it;
            sumSquares += (*it) * (*it);
        }
        
        if (count > 1) {
            double mean = sum / count;
            double variance = (sumSquares / count) - (mean * mean);
            totalVariance += variance;
            gwCount++;
        }
    }
    
    if (gwCount == 0) return false;
    
    double avgVariance = totalVariance / gwCount;
    bool isStable = avgVariance < snrStabilityThreshold;
    
    DEBUG_LOG("[STABILITY] Node " << node.srcAddr << " SNR variance: " 
              << avgVariance << " (stable: " << isStable << ")");
    
    return isStable;
}

// Select least congested SF that meets PER requirements
int NetworkServerApp::selectLeastCongestedSF(const knownNode& node, double targetPER) {
    updateSFUsageStats();
    
    struct SFCandidate {
        int sf;
        double load;
        double collisionRate;
        double score;
    };
    
    std::vector<SFCandidate> candidates;
    
    // Evaluate each SF
    for (int sf = 7; sf <= 12; sf++) {
        double load = (double)sfUsageCount[sf] / knownNodes.size();
        double collision = sfCollisionRate[sf];
        
        // Score: lower is better (combine load and collision rate)
        double score = load + collision;
        
        candidates.push_back({sf, load, collision, score});
    }
    
    // Sort by score (best first)
    std::sort(candidates.begin(), candidates.end(), 
              [](const SFCandidate& a, const SFCandidate& b) {
                  return a.score < b.score;
              });
    
    DEBUG_LOG("[CONGESTION] SF Selection for node " << node.srcAddr << ":");
    for (const auto& c : candidates) {
        DEBUG_LOG("  SF" << c.sf << " score: " << c.score 
                  << " (load: " << c.load << ", collision: " << c.collisionRate << ")");
    }
    
    // Return best SF
    return candidates[0].sf;
}

// Modified chooseBestConfiguration with congestion awareness
std::tuple<int, int, int> NetworkServerApp::congestionAwareConfiguration(
    const knownNode& node,
    const std::map<std::tuple<int, int, int>, double>& PERpredic,
    double PERtarget,
    int payloadSize)
{
    DEBUG_LOG("\n===== [DEBUG START] congestionAwareConfiguration =====");
    
    // First try standard algorithm
    auto standardConfig = chooseBestConfiguration(PERpredic, PERtarget, payloadSize);
    int standardSF = std::get<0>(standardConfig);
    
    // Update current SF tracking
    nodeCurrentSF[node.srcAddr] = standardSF;
    
    // Check congestion conditions
    bool currentSFCongested = isChannelCongested(standardSF);
    bool snrStable = isNodeSNRStable(node);
    bool poorPerformance = calculateCurrentPER(node) > 0.7;
    
    DEBUG_LOG("[CONGESTION CHECK] Node " << node.srcAddr 
              << " SF" << standardSF << " congested: " << currentSFCongested
              << ", SNR stable: " << snrStable  
              << ", poor perf: " << poorPerformance);
    
    // If congested AND SNR is stable, force SF change
    if (currentSFCongested && snrStable && poorPerformance) {
        // Check debounce
        if (lastSFChange.count(node.srcAddr) && 
            simTime() - lastSFChange[node.srcAddr] < sfChangeDebounce) {
            DEBUG_LOG("[CONGESTION] Debounce active, keeping current config");
            return standardConfig;
        }
        
        // Select alternative SF
        int newSF = selectLeastCongestedSF(node, PERtarget);
        
        // Find best TP/NbTrans for new SF
        double bestToA = DBL_MAX;
        std::tuple<int, int, int> bestConfig = standardConfig;
        
        for (const auto& [config, per] : PERpredic) {
            if (std::get<0>(config) == newSF && per <= PERtarget * 1.5) { // Relax PER constraint
                double toa = calculateTimeOnAir(newSF, payloadSize) * std::get<2>(config);
                if (toa < bestToA) {
                    bestToA = toa;
                    bestConfig = config;
                }
            }
        }
        
        lastSFChange[node.srcAddr] = simTime();
        
        DEBUG_LOG("[CONGESTION] FORCING SF CHANGE: SF" << standardSF 
                  << " -> SF" << newSF << " for node " << node.srcAddr);
        
        return bestConfig;
    }
    
    return standardConfig;
}


// ===================================================================
// STEP 4: Implement Dynamic Window Size Calculation
// ===================================================================

int NetworkServerApp::calculateDynamicWindowSize(const knownNode& node, const L3Address& gwAddress) {
    if (!useDynamicWindow) {
        return baseWindowSize;  // Use fixed window if dynamic is disabled
    }
    // ADD: Validate window size parameters
    if (minWindowSize <= 0 || maxWindowSize <= minWindowSize || baseWindowSize <= 0) {
        EV_WARN << "Invalid window size parameters, using baseWindowSize" << endl;
        return baseWindowSize;
    }
    // Check if we have enough data for variance calculation
    if (node.gwAdrListSNIR.count(gwAddress) == 0 || 
        node.gwAdrListSNIR.at(gwAddress).size() < 5) {
        return baseWindowSize;  // Use base size for new/sparse data
    }
    
    // Calculate variance (reuse logic from getAdaptiveAlpha)
    const auto& snrList = node.gwAdrListSNIR.at(gwAddress);
    double sum = 0.0, sumSquares = 0.0;
    int count = 0;
    
    // Use last 5 samples for variance calculation
    auto it = snrList.rbegin();
    for (int i = 0; i < 5 && it != snrList.rend(); ++i, ++it) {
        sum += *it;
        sumSquares += (*it) * (*it);
        count++;
    }
    
    if (count <= 1) {
        return baseWindowSize;
    }
    
    double mean = sum / count;
    double variance = (sumSquares / count) - (mean * mean);
    
    // Determine target window size
    int targetSize;
    if (variance < stableVarianceThreshold) {
        targetSize = maxWindowSize;      // Stable → large window (more reliable stats)
    } else if (variance > unstableVarianceThreshold) {
        targetSize = minWindowSize;      // Unstable → small window (faster adaptation)
    } else {
        // Linear interpolation - FIXED direction
        double ratio = (variance - stableVarianceThreshold) / 
            (unstableVarianceThreshold - stableVarianceThreshold);
        targetSize = maxWindowSize - (int)((maxWindowSize - minWindowSize) * ratio);
    }
        
    // PATCH 4: DEBOUNCE window size changes
    if (targetSize == node.lastDynamicWindowSize) {
        // Same target - increment stability counter
        const_cast<knownNode&>(node).windowSizeStableCount++;
    } else {
        // Different target - reset counter
        const_cast<knownNode&>(node).windowSizeStableCount = 0;
    }
    
    // Only change if stable for enough evaluations
    int finalSize;
    if (node.windowSizeStableCount >= knownNode::WINDOW_DEBOUNCE_THRESHOLD) {
        finalSize = targetSize;
        const_cast<knownNode&>(node).lastDynamicWindowSize = targetSize;
        DEBUG_LOG("[DEBOUNCE] Window size change confirmed: " << finalSize);
    } else {
        finalSize = node.lastDynamicWindowSize;
        DEBUG_LOG("[DEBOUNCE] Window size change pending (" << node.windowSizeStableCount 
                  << "/" << knownNode::WINDOW_DEBOUNCE_THRESHOLD << "): keeping " << finalSize);
    }
    
    return std::max(minWindowSize, std::min(maxWindowSize, finalSize));
}

void NetworkServerApp::updateKnownNodes(Packet* pkt)
{
    const auto & frame = pkt->peekAtFront<LoRaMacFrame>();
    bool nodeExist = false;


    // ===== UPDATED: Use debug macro with proper stream syntax =====
    DEBUG_LOG("\n===== [DEBUG START] updateKnownNodes (seq=" << frame->getSequenceNumber()
              << ", srcAddr=" << frame->getTransmitterAddress() << ") =====");

    for(auto &elem : knownNodes)
    {
        if(elem.srcAddr == frame->getTransmitterAddress()) {
            nodeExist = true;
            if(elem.lastSeqNoProcessed < frame->getSequenceNumber()) {
                elem.lastSeqNoProcessed = frame->getSequenceNumber();
            }
            break;
        }
    }

    if(nodeExist == false) {
        knownNode newNode;
        newNode.srcAddr = frame->getTransmitterAddress();
        newNode.lastSeqNoProcessed = frame->getSequenceNumber();
        newNode.firstSeqNoProcessed = frame->getSequenceNumber();  // Initialize first seq number
        newNode.framesFromLastADRCommand = 0;
        newNode.numberOfSentADRPackets = 0;
        
        // Initialize existing vectors
        newNode.historyAllSNIR = new cOutVector;
        newNode.historyAllSNIR->setName("Vector of SNIR per node");
        newNode.historyAllSNIR->record(math::fraction2dB(frame->getSNIR()));
        newNode.historyAllRSSI = new cOutVector;
        newNode.historyAllRSSI->setName("Vector of RSSI per node");
        newNode.historyAllRSSI->record(frame->getRSSI());
        newNode.receivedSeqNumber = new cOutVector;
        newNode.receivedSeqNumber->setName("Received Sequence number");
        newNode.calculatedSNRmargin = new cOutVector;
        newNode.calculatedSNRmargin->setName("Calculated SNRmargin in ADR");
        
        // Initialize gateway-specific tracking
        const auto& networkHeader = getNetworkProtocolHeader(pkt);
        const L3Address& gwAddress = networkHeader->getSourceAddress();
        
        newNode.gwAdrListSNIR[gwAddress] = std::list<double>();
        newNode.gwAdrListSNIR[gwAddress].push_back(frame->getSNIR());
        newNode.seqNumWindow.push_back(frame->getSequenceNumber());

        newNode.gwHistorySNIR[gwAddress] = new cOutVector;
        newNode.gwHistorySNIR[gwAddress]->setName(("SNIR from GW " + gwAddress.str()).c_str());
        newNode.gwHistorySNIR[gwAddress]->record(frame->getSNIR());
        
        if (useWeightedSNR) {
            updateWeightedSNR(newNode, gwAddress, frame->getSNIR());
        }

        knownNodes.push_back(newNode);

        DEBUG_LOG("[INFO] Created new knownNode for " << frame->getTransmitterAddress()
            << " (first seq=" << frame->getSequenceNumber() << ")");
        DEBUG_LOG("[INFO] Created GW SNIR buffer for GW " << gwAddress
            << " for node " << frame->getTransmitterAddress());
        DEBUG_LOG("[DATA] SNIR window for GW " << gwAddress << " size=1");
        DEBUG_LOG("[DATA] SeqNum window size=1: " << frame->getSequenceNumber());


    } else {
        for(auto &node : knownNodes) {
            if(node.srcAddr == frame->getTransmitterAddress()) {
                if(node.lastSeqNoProcessed < frame->getSequenceNumber()) {
                    node.lastSeqNoProcessed = frame->getSequenceNumber();
                }
                
                // GW SNIR tracking
                const auto& networkHeader = getNetworkProtocolHeader(pkt);
                const L3Address& gwAddress = networkHeader->getSourceAddress();
                
                if(node.gwAdrListSNIR.find(gwAddress) == node.gwAdrListSNIR.end()) {
                    node.gwAdrListSNIR[gwAddress] = std::list<double>();
                    node.gwHistorySNIR[gwAddress] = new cOutVector;
                    node.gwHistorySNIR[gwAddress]->setName(("SNIR from GW " + gwAddress.str()).c_str());
                    DEBUG_LOG("[INFO] Created GW SNIR buffer for NEW GW " << gwAddress
                        << " for node " << frame->getTransmitterAddress());
                }
                
                // Add new SNIR measurement
                node.gwAdrListSNIR[gwAddress].push_back(frame->getSNIR());
                node.gwHistorySNIR[gwAddress]->record(frame->getSNIR());

                // NEW: DYNAMIC WINDOW SIZE APPLICATION
                int currentWindowSize = calculateDynamicWindowSize(node, gwAddress);
                while(node.gwAdrListSNIR[gwAddress].size() > (size_t)currentWindowSize) {
                    node.gwAdrListSNIR[gwAddress].pop_front();
                }
                
                DEBUG_LOG("[DATA] SNIR window for GW " << gwAddress << " now has size="
                    << node.gwAdrListSNIR[gwAddress].size() << " (dynamic_target=" << currentWindowSize << ")");
                               
                if (useWeightedSNR) {
                    updateWeightedSNR(node, gwAddress, frame->getSNIR());
                    if (node.gwLastUpdate.size() > 1) {
                        cleanupStaleGateways(node);
                    }
                }

                break;
            }
        }
    }
    DEBUG_LOG("===== [DEBUG END] " << " =====\n");
}


void NetworkServerApp::addPktToProcessingTable(Packet* pkt)
{
    const auto & frame = pkt->peekAtFront<LoRaMacFrame>();
    bool packetExists = false;
    for(auto &elem : receivedPackets)
    {
        const auto &frameAux = elem.rcvdPacket->peekAtFront<LoRaMacFrame>();
        if(frameAux->getTransmitterAddress() == frame->getTransmitterAddress() && frameAux->getSequenceNumber() == frame->getSequenceNumber())
        {
            packetExists = true;
            const auto& networkHeader = getNetworkProtocolHeader(pkt);
            const L3Address& gwAddress = networkHeader->getSourceAddress();
            elem.possibleGateways.emplace_back(gwAddress, frame->getSNIR(), frame->getRSSI());
            delete pkt;
            break;
        }
    }
    if(packetExists == false)
    {
        receivedPacket rcvPkt;
        rcvPkt.rcvdPacket = pkt;
        rcvPkt.endOfWaiting = new cMessage("endOfWaitingWindow");
        rcvPkt.endOfWaiting->setControlInfo(pkt);
        const auto& networkHeader = getNetworkProtocolHeader(pkt);
        const L3Address& gwAddress = networkHeader->getSourceAddress();
        rcvPkt.possibleGateways.emplace_back(gwAddress, frame->getSNIR(), frame->getRSSI());
        EV << "Added " << gwAddress << " " << frame->getSNIR() << " " << frame->getRSSI() << endl;
        scheduleAt(simTime() + 1.2, rcvPkt.endOfWaiting);
        receivedPackets.push_back(rcvPkt);
    }
}

void NetworkServerApp::processScheduledPacket(cMessage* selfMsg)
{
    auto pkt = check_and_cast<Packet *>(selfMsg->removeControlInfo());
    const auto & frame = pkt->peekAtFront<LoRaMacFrame>();

    if (simTime() >= getSimulation()->getWarmupPeriod())
    {
        counterUniqueReceivedPacketsPerSF[frame->getLoRaSF()-7]++;
    }
    L3Address pickedGateway;
    double SNIRinGW = -99999999999;
    double RSSIinGW = -99999999999;
    int packetNumber;
    int nodeNumber;
    for(uint i=0;i<receivedPackets.size();i++)
    {
        const auto &frameAux = receivedPackets[i].rcvdPacket->peekAtFront<LoRaMacFrame>();
        if(frameAux->getTransmitterAddress() == frame->getTransmitterAddress() && frameAux->getSequenceNumber() == frame->getSequenceNumber())        {
            packetNumber = i;
            nodeNumber = frame->getTransmitterAddress().getInt();
            if (numReceivedPerNode.count(nodeNumber-1)>0)
            {
                ++numReceivedPerNode[nodeNumber-1];
            } else {
                numReceivedPerNode[nodeNumber-1] = 1;
            }

            // First determine the best gateway
            for(uint j=0;j<receivedPackets[i].possibleGateways.size();j++)
            {
                if(SNIRinGW < std::get<1>(receivedPackets[i].possibleGateways[j]))
                {
                    RSSIinGW = std::get<2>(receivedPackets[i].possibleGateways[j]);
                    SNIRinGW = std::get<1>(receivedPackets[i].possibleGateways[j]);
                    pickedGateway = std::get<0>(receivedPackets[i].possibleGateways[j]);
                }
            }

            // Then update the node with the correct gateway
            for (auto &node : knownNodes) {
                if (node.srcAddr == frame->getTransmitterAddress()) {
                    node.seqNumWindow.push_back(frame->getSequenceNumber());
                    
                    // Update node-wide window size based on picked gateway
                    node.currentNodeWideWindowSize = calculateDynamicWindowSize(node, pickedGateway);
                    
                    while (node.seqNumWindow.size() > (size_t)node.currentNodeWideWindowSize)
                        node.seqNumWindow.pop_front();
                    break;
                }
            }
        }
    }
    emit(LoRa_ServerPacketReceived, true);
    if (simTime() >= getSimulation()->getWarmupPeriod())
    {
        counterUniqueReceivedPackets++;
    }
    receivedRSSI.collect(frame->getRSSI());
    if(evaluateADRinServer)
    {
        evaluateADR(pkt, pickedGateway, SNIRinGW, RSSIinGW);
    }
    delete receivedPackets[packetNumber].rcvdPacket;
    delete selfMsg;
    receivedPackets.erase(receivedPackets.begin()+packetNumber);
}

void NetworkServerApp::receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details)
{
    if (simTime() >= getSimulation()->getWarmupPeriod())
    {
        counterOfSentPacketsFromNodes++;
        counterOfSentPacketsFromNodesPerSF[value-7]++;
    }
}


// ===================================================================
// PATCH 5: WEIGHTED SNR OUTLIER FILTERING  
// ===================================================================

void NetworkServerApp::updateWeightedSNR(knownNode& node, const L3Address& gwAddress, double currentSNIR) {
    node.gwLastUpdate[gwAddress] = simTime();
    
    // PATCH 5: OUTLIER FILTERING
    if (node.gwAdrListSNIR.count(gwAddress) && node.gwAdrListSNIR.at(gwAddress).size() >= 3) {
        const auto& snrList = node.gwAdrListSNIR.at(gwAddress);
        
        // Calculate median of last 5 values for outlier detection
        std::vector<double> recentValues;
        auto it = snrList.rbegin();
        for (int i = 0; i < 5 && it != snrList.rend(); ++i, ++it) {
            recentValues.push_back(*it);
        }
        
        if (recentValues.size() >= 3) {
            std::sort(recentValues.begin(), recentValues.end());
            double median = recentValues[recentValues.size()/2];
            double deviation = std::abs(currentSNIR - median);
            
            // If current value is extreme outlier (>15dB from median), filter it
            if (deviation > 15.0) {
                DEBUG_LOG("[OUTLIER] Filtering extreme SNIR value: " << currentSNIR 
                          << " (median=" << median << ", dev=" << deviation << ")");
                currentSNIR = median + (currentSNIR > median ? 10.0 : -10.0);  // Cap deviation
            }
        }
    }
    
    // Continue with existing weighted SNR logic using filtered currentSNIR
    if (node.gwWeightedInitialized.find(gwAddress) == node.gwWeightedInitialized.end() || 
        !node.gwWeightedInitialized[gwAddress]) {
        node.gwWeightedSNIR[gwAddress] = currentSNIR;
        node.gwWeightedInitialized[gwAddress] = true;
        DEBUG_LOG("[WEIGHTED] Init GW " << gwAddress << " SNR: " << currentSNIR);
    } else {
        double alpha = useAdaptiveAlpha ? getAdaptiveAlpha(node, gwAddress) : weightingAlpha;
        double oldWeighted = node.gwWeightedSNIR[gwAddress];
        double newWeighted = alpha * currentSNIR + (1.0 - alpha) * oldWeighted;
        node.gwWeightedSNIR[gwAddress] = newWeighted;
        DEBUG_LOG("[WEIGHTED] GW " << gwAddress << " alpha=" << alpha 
                  << " old=" << oldWeighted << " new=" << newWeighted);
    }
}

double NetworkServerApp::getAdaptiveAlpha(const knownNode& node, const L3Address& gwAddress) {
    if (node.gwAdrListSNIR.count(gwAddress) && node.gwAdrListSNIR.at(gwAddress).size() >= 5) {
        const auto& snrList = node.gwAdrListSNIR.at(gwAddress);
        double sum = 0.0, sumSquares = 0.0;
        int count = 0;
        auto it = snrList.rbegin();
        for (int i = 0; i < 5 && it != snrList.rend(); ++i, ++it) {
            sum += *it;
            sumSquares += (*it) * (*it);
            count++;
        }
        if (count > 1) {
            double mean = sum / count;
            double variance = (sumSquares / count) - (mean * mean);
            if (variance > 3.0) return unstableAlpha;
            if (variance < 1.0) return stableAlpha;
        }
    }
    return weightingAlpha;
}

void NetworkServerApp::cleanupStaleGateways(knownNode& node) {
    if (!useWeightedSNR) return;
    simtime_t now = simTime();
    auto it = node.gwLastUpdate.begin();
    while (it != node.gwLastUpdate.end()) {
        if (now - it->second > gwTimeoutSeconds) {
            L3Address gwAddr = it->first;
            DEBUG_LOG("[CLEANUP] Removing stale GW " << gwAddr);
            node.gwWeightedSNIR.erase(gwAddr);
            node.gwWeightedInitialized.erase(gwAddr);
            it = node.gwLastUpdate.erase(it);
        } else {
            ++it;
        }
    }
}

double NetworkServerApp::getWeightedSNRForGateway(const knownNode& node, const L3Address& gwAddress) {
    if (!useWeightedSNR) {
        if (node.gwAdrListSNIR.count(gwAddress) && !node.gwAdrListSNIR.at(gwAddress).empty()) {
            return *std::max_element(node.gwAdrListSNIR.at(gwAddress).begin(), 
                                   node.gwAdrListSNIR.at(gwAddress).end());
        }
        return 0.0;
    }
    if (node.gwWeightedSNIR.count(gwAddress)) {
        return node.gwWeightedSNIR.at(gwAddress);
    }
    return 0.0;
}
void NetworkServerApp::evaluateADR(Packet* pkt, L3Address pickedGateway, double SNIRinGW, double RSSIinGW)
{
    std::string blockName = "evaluateADR (srcAddr=" + 
        pkt->peekAtFront<LoRaMacFrame>()->getTransmitterAddress().str() +
        ", seq=" + std::to_string(pkt->peekAtFront<LoRaMacFrame>()->getSequenceNumber()) + ")";
    DEBUG_LOG("\n===== [DEBUG START] " << blockName << " =====");

    bool sendADR = false;
    bool sendADRAckRep = false;
    int nodeIndex = -1;
    int bestSF = 12;
    int bestTP = 14;  // FIXED: Always use maximum TX power
    int bestNbTrans = 3;
    std::tuple<int, int, int> bestConfig;
    std::map<std::tuple<int, int, int>, double> PERpredic;
    // FIXED: Declare gwSNIR variable
    double gwSNIR = 0.0;

    pkt->trimFront();
    auto frame = pkt->removeAtFront<LoRaMacFrame>();
    
    // Extract actual payload size
    const auto & appPacket = pkt->peekAtFront<LoRaAppPacket>();
    int payloadSize = B(appPacket->getChunkLength()).get();
    if (payloadSize == 0) payloadSize = 20; // Default fallback

    if(appPacket->getOptions().getADRACKReq())
        sendADRAckRep = true;

    // Process packet for each known node
    for(uint i=0; i<knownNodes.size(); i++)
    {
        if(knownNodes[i].srcAddr == frame->getTransmitterAddress())
        {
            // Record the SNIR and RSSI for this reception
            knownNodes[i].historyAllSNIR->record(SNIRinGW);
            knownNodes[i].historyAllRSSI->record(RSSIinGW);
            knownNodes[i].receivedSeqNumber->record(frame->getSequenceNumber());
            knownNodes[i].adrListSNIR.push_back(SNIRinGW);
            int windowSize = calculateDynamicWindowSize(knownNodes[i], pickedGateway);
            while(knownNodes[i].adrListSNIR.size() > (size_t)windowSize) 
                knownNodes[i].adrListSNIR.pop_front();
            knownNodes[i].framesFromLastADRCommand++;

            // Check if we need to send an ADR command
            int currentWindowSize = calculateDynamicWindowSize(knownNodes[i], pickedGateway);
            if(knownNodes[i].framesFromLastADRCommand >= currentWindowSize || sendADRAckRep == true)
            {
                DEBUG_LOG("\n===== [DEBUG ADR DECISION SET START] for node: " 
                    << knownNodes[i].srcAddr << " =====");

                nodeIndex = i;
                knownNodes[i].framesFromLastADRCommand = 0;
                sendADR = true;

                double PERcurrent = calculateCurrentPER(knownNodes[i]);
                double PERmax = 0.3;
                
                // PATCH 3: ADAPTIVE PER TARGET based on current performance
                double adaptivePERtarget = PERmax;
                
                // If node performing poorly, be more aggressive (lower target)
                if (PERcurrent > 0.5) {
                    adaptivePERtarget = std::max(0.05, PERmax * 0.5);  // Half the target
                    DEBUG_LOG("[ADAPTIVE] High PER node - aggressive target: " << adaptivePERtarget);
                }
                // If node performing well, can be more conservative  
                else if (PERcurrent < 0.1) {
                    adaptivePERtarget = PERmax * 1.5;  // 50% higher target
                    DEBUG_LOG("[ADAPTIVE] Low PER node - conservative target: " << adaptivePERtarget);
                }
                
                // Traditional adjustment
                if (PERcurrent > PERmax) {
                    adaptivePERtarget = std::max(0.01, adaptivePERtarget - (PERcurrent - PERmax));
                }
                
                DEBUG_LOG("[DATA] PERcurrent = " << PERcurrent 
                            << ", PERmax = " << PERmax
                            << ", adaptivePERtarget = " << adaptivePERtarget);

                double currentTPdBm = math::mW2dBmW(frame->getLoRaTP());
                int windowSize = calculateDynamicWindowSize(knownNodes[i], pickedGateway);
                double sizeS_base = (double)windowSize / (1.0 - PERcurrent);

                // Test all SF, TP, and NbTrans combinations
                for (int SF = 7; SF <= 12; SF++) {
                    for (int TPdBm = 2; TPdBm <= 14; TPdBm++) {  // ADAUGĂ acest loop!
                        for (int NbTrans = 1; NbTrans <= 3; NbTrans++) {
                            double productPER = 1.0;
                            double sizeS = sizeS_base * NbTrans;
                            
                            DEBUG_LOG("[CHECK] (SF=" << SF << ", TPdBm=" << TPdBm 
                                        << ", NbTrans=" << NbTrans << "):");
                                
                            
                            // Calculate PER across all gateways
                            for (const auto& [gwAddress, snirList] : knownNodes[i].gwAdrListSNIR) {
                                if (snirList.empty()) continue;
                
                                // FIXED: Now gwSNIR is properly declared
                                gwSNIR = getWeightedSNRForGateway(knownNodes[i], gwAddress);
                                if (useWeightedSNR) {
                                    double maxSNIR = *std::max_element(snirList.begin(), snirList.end());
                                    DEBUG_LOG("   [SNR] GW " << gwAddress << " Weighted: " << gwSNIR << " Max: " << maxSNIR);
                                } else {
                                    DEBUG_LOG("   [SNR] GW " << gwAddress << " Max: " << gwSNIR);
                                }
                                double deltaTP = TPdBm - currentTPdBm;
                                double adjustedSNIR = gwSNIR + deltaTP;
                                double gwSNR_d = estimateGWSNR_d(knownNodes[i], gwAddress, adjustedSNIR, sizeS);
                                double gwFER = calculateFER(SF, gwSNR_d);
                                double gwPER = pow(gwFER, NbTrans);

                                productPER *= gwPER;

                                DEBUG_LOG("   [GW: " << gwAddress
                                    << "] gwSNIR=" << gwSNIR
                                    << ", deltaTP=" << deltaTP
                                    << ", adjSNIR=" << adjustedSNIR
                                    << ", SNR_d=" << gwSNR_d
                                    << ", FER=" << gwFER
                                    << ", PER=" << gwPER);
                            }
                            
                            DEBUG_LOG("   [RESULT] productPER = " << productPER);
                            PERpredic[std::make_tuple(SF, TPdBm, NbTrans)] = productPER;
                        }

                    }
                }

                if (useCongestionAwareness) {
                    bestConfig = congestionAwareConfiguration(knownNodes[i], PERpredic, 
                                                            adaptivePERtarget, payloadSize);
                } else {
                    bestConfig = chooseBestConfiguration(PERpredic, adaptivePERtarget, payloadSize);
                }
                bestSF = std::get<0>(bestConfig);
                bestTP = std::get<1>(bestConfig);
                bestNbTrans = std::get<2>(bestConfig);
                
                // Update the node's current NbTrans
                knownNodes[nodeIndex].currentNbTrans = bestNbTrans;

                DEBUG_LOG("[RESULT] Selected Config: SF=" << bestSF
                    << ", TPdBm=" << bestTP
                    << ", NbTrans=" << bestNbTrans);
                DEBUG_LOG("===== [DEBUG ADR DECISION SET END] =====");

                break;
            }
        }
    }

    // Handle sending the ADR packet (unchanged)
    if(sendADR || sendADRAckRep)
    {
        auto mgmtPacket = makeShared<LoRaAppPacket>();
        mgmtPacket->setMsgType(TXCONFIG);

        if(sendADR)
        {
            LoRaOptions newOptions;
            newOptions.setLoRaSF(bestSF);
            newOptions.setLoRaTP(bestTP);
            // If LoRaOptions supports NbTrans:
            // newOptions.setNbTrans(bestNbTrans);
            mgmtPacket->setOptions(newOptions);
        }

        if(simTime() >= getSimulation()->getWarmupPeriod() && sendADR == true)
        {
            knownNodes[nodeIndex].numberOfSentADRPackets++;
        }

        auto frameToSend = makeShared<LoRaMacFrame>();
        frameToSend->setChunkLength(B(par("headerLength").intValue()));
        frameToSend->setReceiverAddress(frame->getTransmitterAddress());
        frameToSend->setLoRaSF(bestSF);
        frameToSend->setLoRaTP(math::dBmW2mW(bestTP));
        frameToSend->setLoRaCF(frame->getLoRaCF());
        frameToSend->setLoRaBW(frame->getLoRaBW());

        auto pktAux = new Packet("ADRPacket");
        mgmtPacket->setChunkLength(B(par("headerLength").intValue()));
        pktAux->insertAtFront(mgmtPacket);
        pktAux->insertAtFront(frameToSend);
        socket.sendTo(pktAux, pickedGateway, destPort);
    }

    DEBUG_LOG("===== [DEBUG END] " << blockName << " =====\n");
}

// ===== FIX 3: Fixed calculateCurrentPER function =====
double NetworkServerApp::calculateCurrentPER(const knownNode& node) {
    DEBUG_LOG("\n===== [DEBUG START] calculateCurrentPER =====");
    
    if (node.seqNumWindow.empty()) {
        DEBUG_LOG("[INFO] seqNumWindow is empty, returning PER=0.0");
        DEBUG_LOG("===== [DEBUG END] calculateCurrentPER =====\n");
        return 0.0;
    }
    
    // Get the range of sequence numbers in our window
    auto minmax = std::minmax_element(node.seqNumWindow.begin(), node.seqNumWindow.end());
    int minSeq = *minmax.first;
    int maxSeq = *minmax.second;
    int rangeSize = maxSeq - minSeq + 1;
    if (maxSeq - minSeq > 32768) {
        // Separate high and low sequence numbers
        std::vector<int> highSeqs, lowSeqs;
        for (int seq : node.seqNumWindow) {
            if (seq > 32768) {
                highSeqs.push_back(seq);
            } else {
                lowSeqs.push_back(seq);
            }
        }
        
        if (!highSeqs.empty() && !lowSeqs.empty()) {
            int seqStart = *std::min_element(highSeqs.begin(), highSeqs.end());
            int seqEnd = *std::max_element(lowSeqs.begin(), lowSeqs.end());
            
            // Range from seqStart to 65535, then 0 to seqEnd
            rangeSize = (65535 - seqStart + 1) + (seqEnd + 1);
        } else {
            rangeSize = maxSeq - minSeq + 1; // Fallback
        }
    } else {
        rangeSize = maxSeq - minSeq + 1; // Normal case
    }
    
    // Count unique sequences in the window
    std::set<int> uniqueSeqs(node.seqNumWindow.begin(), node.seqNumWindow.end());
    int numUnique = uniqueSeqs.size();
    
    DEBUG_LOG("[DATA] Window seq range: [" << minSeq << ", " << maxSeq 
                 << "], rangeSize=" << rangeSize 
                 << ", uniqueCount=" << numUnique);
    
    if (rangeSize <= 0) {
        DEBUG_LOG("[RESULT] rangeSize <= 0, returning PER=0.0");
        DEBUG_LOG("===== [DEBUG END] calculateCurrentPER =====\n");
        return 0.0;
    }
    
    // PER based on window range only
    double result = 1.0 - (double)numUnique / rangeSize;
    DEBUG_LOG("[RESULT] PER=" << result);
    DEBUG_LOG("===== [DEBUG END] calculateCurrentPER =====\n");
    return result;
}

// FIX 1: CORECTEAZĂ FORMULA FER
double NetworkServerApp::calculateFER(int SF, double SNR) {
    DEBUG_LOG("\n===== [DEBUG START] calculateFER =====");
    
    // Formula corectă pentru LoRa FER calculation
    double SNRfloor = -20.0 + ((12 - SF) * 2.5); // LoRa theoretical
    
    // FIX: Folosește formula corectă pentru FER
    // Formula originală exp(-10^x) era mult prea agresivă
    double snr_margin = SNR - SNRfloor;
    double FER;
    
    if (snr_margin < 0) {
        FER = 1.0; // Poor signal, high error rate
    } else {
        // Folosește o funcție mai realistă: FER decreases exponentially with SNR margin
        FER = exp(-snr_margin / 5.0);  // 5dB decay constant
    }
    
    // Clamp la valori rezonabile
    FER = std::max(0.001, std::min(0.99, FER));
    
    DEBUG_LOG("[GOAL] Calculating FER for SF=" << SF << " and SNR=" << SNR);
    DEBUG_LOG("[DATA] SNRfloor=" << SNRfloor << ", snr_margin=" << snr_margin << ", FER=" << FER);
    DEBUG_LOG("[RESULT] FER=" << FER);
    DEBUG_LOG("===== [DEBUG END] calculateFER =====\n");
    return FER;
}


// ===================================================================
// PATCH 1: BIAS ENERGETIC AGRESIV (PRIORITATE #1)
// ===================================================================

std::tuple<int, int, int> NetworkServerApp::chooseBestConfiguration(
    const std::map<std::tuple<int, int, int>, double>& PERpredic, 
    double PERtarget, 
    int payloadSize)
{
    DEBUG_LOG("\n===== [DEBUG START] chooseBestConfiguration =====");
    double bestToA = DBL_MAX;
    std::tuple<int, int, int> bestConfig = std::make_tuple(12, 14, 3);
    std::tuple<int, int, int> fallbackConfig = std::make_tuple(12, 14, 3);
    double fallbackPER = 1.0;

    DEBUG_LOG("[GOAL] Selecting (SF, TP, NbTrans) with lowest ToA, PER <= " << PERtarget);
    DEBUG_LOG("[WEIGHT] useWeightBias=" << useWeightBias << ", bias=" << weightRobustnessBias);

    int validConfigs = 0;
    
    for (const auto& [config, per] : PERpredic) {
        int SF = std::get<0>(config);
        int TPdBm = std::get<1>(config);
        int NbTrans = std::get<2>(config);
        
        double ToA = calculateTimeOnAir(SF, payloadSize) * NbTrans;
        double originalToA = ToA;
        
        if (TPdBm < 10 && per > 0.1) {
            DEBUG_LOG("[SAFETY] Rejecting risky TP=" << TPdBm 
                    << " with PER=" << per << " for SF=" << SF);
            continue;
        }

        // PATCH 1: BIAS ENERGETIC - FIXED  
        if (useWeightBias) {
            double configBias = (12 - SF) * weightRobustnessBias;
            ToA *= (1.0 + configBias);
            DEBUG_LOG("[BIAS] SF=" << SF << " configBias=" << configBias 
                    << " originalToA=" << originalToA*1000 << "ms adjustedToA=" << ToA*1000 << "ms");
        }
        // Track best fallback config (lowest PER regardless of target)
        if (per < fallbackPER) {
            fallbackPER = per;
            fallbackConfig = config;
        }
        
        DEBUG_LOG("[EVAL] Testing SF=" << SF << " TP=" << TPdBm 
                  << " NbTrans=" << NbTrans << " PER=" << per);
                  
        if (per <= PERtarget) {
            validConfigs++;
            
            DEBUG_LOG("[CHECK] SF=" << SF << ", TPdBm=" << TPdBm << ", NbTrans=" << NbTrans
                         << ", ToA=" << ToA*1000 << "ms, PER=" << per);
            
            if (ToA < bestToA) {
                bestToA = ToA;
                bestConfig = config;
                DEBUG_LOG("[INFO] New best config found: SF=" << SF << " TP=" << TPdBm);
            }
        } else {
            DEBUG_LOG("[REJECT] PER " << per << " > target " << PERtarget);
        }
    }
    
    // PATCH 2: FALLBACK CÂND NICIUN CONFIG NU E VALID
    if (validConfigs == 0) {
        DEBUG_LOG("[FALLBACK] No valid configs found! Using best PER config: SF=" 
                  << std::get<0>(fallbackConfig) << " TP=" << std::get<1>(fallbackConfig) 
                  << " PER=" << fallbackPER);
        bestConfig = fallbackConfig;
    }
    
    DEBUG_LOG("[SUMMARY] Found " << validConfigs << " valid configs out of " << PERpredic.size());
    DEBUG_LOG("[RESULT] Selected Config: SF=" << std::get<0>(bestConfig) 
              << " TP=" << std::get<1>(bestConfig) << " NbTrans=" << std::get<2>(bestConfig));
    DEBUG_LOG("===== [DEBUG END] chooseBestConfiguration =====\n");
    return bestConfig;
}

// FIX 2: CORECTEAZĂ TIME ON AIR CALCULATION
double NetworkServerApp::calculateTimeOnAir(int SF, int payloadBytes) {
    DEBUG_LOG("\n===== [DEBUG START] calculateTimeOnAir =====");
    
    // Constants for LoRa
    double Tsym = pow(2, SF) / 125000.0; // Symbol period in seconds (BW=125kHz)
    
    // FIX: Coding Rate corect pentru LoRaWAN 4/5
    int CR = 1; // LoRaWAN uses CR 4/5, so CR=1 in formula
    
    // Calculate preamble time
    int preambleSymbols = 8; // Default
    double Tpreamble = (preambleSymbols + 4.25) * Tsym;
    
    // Calculate payload symbol count
    int H = 0; // 0 for explicit header, 1 for implicit
    int DE = (SF >= 11) ? 1 : 0; // Low data rate optimization
    int PL = payloadBytes;
    
    // FIX: Folosește CR în loc de CodingRate
    double payloadSymbolsFloat = (8.0 * PL - 4.0 * SF + 28.0 + 16.0 - 20.0 * H) / (4.0 * (SF - 2 * DE));
    int payloadSymbols = 8 + std::max(0.0, ceil(payloadSymbolsFloat)) * (CR + 4);
    
    // Total time on air
    double Tpayload = payloadSymbols * Tsym;
    double totalToA = Tpreamble + Tpayload;
    
    DEBUG_LOG("[CALC] SF=" << SF << " PL=" << payloadBytes);
    DEBUG_LOG("[CALC] Tsym=" << Tsym*1000 << "ms, DE=" << DE << ", CR=" << CR);
    DEBUG_LOG("[CALC] payloadSymbols=" << payloadSymbols << ", Tpreamble=" << Tpreamble*1000 << "ms");
    DEBUG_LOG("[RESULT] ToA=" << totalToA*1000 << "ms");
    DEBUG_LOG("===== [DEBUG END] calculateTimeOnAir =====\n");
    
    return totalToA;
}

double NetworkServerApp::estimateGWSNR_d(const knownNode& node, const L3Address& gwAddress, double currentSNIR, double sizeS)
{
    double SNRmax = currentSNIR;
    if (node.gwAdrListSNIR.count(gwAddress) && !node.gwAdrListSNIR.at(gwAddress).empty())
        SNRmax = *std::max_element(node.gwAdrListSNIR.at(gwAddress).begin(), node.gwAdrListSNIR.at(gwAddress).end());

    // **Paper's quantile formula**
    double quantile_95 = -log(1.0 - pow(0.95, 1.0 / sizeS));
    double quantile_05 = -log(1.0 - pow(0.05, 1.0 / sizeS));
    double SNR_Max_SUMED = (10.0 * log10(quantile_95) + 10.0 * log10(quantile_05)) / 2.0;

    return SNRmax - SNR_Max_SUMED;
}


} //namespace inet