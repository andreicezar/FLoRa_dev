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

#include <fstream>

std::ofstream debugLogFile;

namespace flora {

Define_Module(NetworkServerApp);

void NetworkServerApp::initialize(int stage)
{
    if (stage == 0) {
        debugADR = par("debugADR").boolValue();
        
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
        
        if (debugADR) {
            std::string filename = useWeightedSNR ? "debug_adr_opt_log_WEIGHTED.txt" : "debug_adr_opt_log_NO_WEIGHT.txt";
            std::cout << "Attempting to create debug file: " << filename << std::endl;
            
            debugLogFile.open(filename);
            if (debugLogFile.is_open()) {
                std::cout << "Debug file created successfully!" << std::endl;
                debugLogFile << "ADRopt Log started." << std::endl;
                debugLogFile << "Weighted SNR enabled: " << useWeightedSNR << std::endl;
                debugLogFile.flush(); // Force write to disk
            } else {
                std::cout << "ERROR: Failed to create debug file!" << std::endl;
            }
        } else {
            std::cout << "Debug is DISABLED (debugADR = false)" << std::endl;
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
                
                node.gwAdrListSNIR[gwAddress].push_back(frame->getSNIR());
                while(node.gwAdrListSNIR[gwAddress].size() > 20)
                    node.gwAdrListSNIR[gwAddress].pop_front();

                node.gwHistorySNIR[gwAddress]->record(frame->getSNIR());

                
                DEBUG_LOG("[DATA] SNIR window for GW " << gwAddress << " now has size="
                    << node.gwAdrListSNIR[gwAddress].size());
                
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

            for (auto &node : knownNodes) {
                if (node.srcAddr == frame->getTransmitterAddress()) {
                    // Only add if this seq number not in the window already (optional, if window is unique)
                    node.seqNumWindow.push_back(frame->getSequenceNumber());
                    while (node.seqNumWindow.size() > 20)
                        node.seqNumWindow.pop_front();
                    break;
                }
            }


            for(uint j=0;j<receivedPackets[i].possibleGateways.size();j++)
            {
                if(SNIRinGW < std::get<1>(receivedPackets[i].possibleGateways[j]))
                {
                    RSSIinGW = std::get<2>(receivedPackets[i].possibleGateways[j]);
                    SNIRinGW = std::get<1>(receivedPackets[i].possibleGateways[j]);
                    pickedGateway = std::get<0>(receivedPackets[i].possibleGateways[j]);
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


void NetworkServerApp::updateWeightedSNR(knownNode& node, const L3Address& gwAddress, double currentSNIR) {
    node.gwLastUpdate[gwAddress] = simTime();
    
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
        DEBUG_LOG("[WEIGHTED] GW " << gwAddress << " alpha=" << alpha << " old=" << oldWeighted << " new=" << newWeighted);
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

// ===== FIX 5: Updated evaluateADR function =====
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
            knownNodes[i].adrListSNIR.push_back(SNIRinGW);
            knownNodes[i].historyAllSNIR->record(SNIRinGW);
            knownNodes[i].historyAllRSSI->record(RSSIinGW);
            knownNodes[i].receivedSeqNumber->record(frame->getSequenceNumber());
            if(knownNodes[i].adrListSNIR.size() == 20) 
                knownNodes[i].adrListSNIR.pop_front();
            knownNodes[i].framesFromLastADRCommand++;

            // Check if we need to send an ADR command
            if(knownNodes[i].framesFromLastADRCommand == 20 || sendADRAckRep == true)
            {
                DEBUG_LOG("\n===== [DEBUG ADR DECISION SET START] for node: " 
                    << knownNodes[i].srcAddr << " =====");

                nodeIndex = i;
                knownNodes[i].framesFromLastADRCommand = 0;
                sendADR = true;

                double PERcurrent = calculateCurrentPER(knownNodes[i]);
                double PERmax = 0.3;  // As per paper
                double PERtarget = PERmax;

                // Adjust target if current PER is too high
                if (PERcurrent > PERmax) {
                    PERtarget = std::max(0.01, PERmax - (PERcurrent - PERmax));
                }

                // FIXED: Only use maximum TX power (14 dBm) as per paper
                int TPdBm = 14;
                double currentTPdBm = math::mW2dBmW(frame->getLoRaTP());
                double sizeS_base = 20.0 / (1.0 - PERcurrent);

                DEBUG_LOG("[DATA] PERcurrent = " << PERcurrent 
                            << ", PERmax = " << PERmax
                            << ", PERtarget = " << PERtarget);

                // Test all SF and NbTrans combinations
                for (int SF = 7; SF <= 12; SF++) {
                    for (int NbTrans = 1; NbTrans <= 3; NbTrans++) {
                        double productPER = 1.0;
                        double sizeS = sizeS_base * NbTrans;
                        
                        DEBUG_LOG("[CHECK] (SF=" << SF << ", TPdBm=" << TPdBm 
                                    << ", NbTrans=" << NbTrans << "):");
                        
                        // Calculate PER across all gateways
                        for (const auto& [gwAddress, snirList] : knownNodes[i].gwAdrListSNIR) {
                            if (snirList.empty()) continue;
            
                            // Cleaner approach:
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

                bestConfig = chooseBestConfiguration(PERpredic, PERtarget, payloadSize);
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

double NetworkServerApp::calculateFER(int SF, double SNR) {
    DEBUG_LOG("\n===== [DEBUG START] calculateFER =====");
    double SNRfloor = -20.0 + ((12 - SF) * 2.5); // LoRa theoretical
    double FER = exp(-pow(10, (SNR - SNRfloor) / 10.0)); // CDFexp
    DEBUG_LOG("[GOAL] Calculating FER for SF=" << SF << " and SNR=" << SNR);
    DEBUG_LOG("[DATA] SNRfloor=" << SNRfloor << ", FER=" << FER);
    DEBUG_LOG("[RESULT] FER=" << FER);
    DEBUG_LOG("===== [DEBUG END] calculateFER =====\n");
    return FER;
}

// ===== FIX 6: Updated chooseBestConfiguration function =====
std::tuple<int, int, int> NetworkServerApp::chooseBestConfiguration(
    const std::map<std::tuple<int, int, int>, double>& PERpredic, double PERtarget, int payloadSize)
{
    DEBUG_LOG("\n===== [DEBUG START] chooseBestConfiguration =====");
    double bestToA = DBL_MAX;
    std::tuple<int, int, int> bestConfig = std::make_tuple(12, 14, 3); // fallback: most robust

    DEBUG_LOG("[GOAL] Selecting (SF, TP, NbTrans) with lowest ToA, PER <= " << PERtarget);

    // FIXED: Only consider maximum TX power (14 dBm)
    for (int SF = 7; SF <= 12; SF++) {
        int TPdBm = 14;  // Fixed at maximum
        for (int NbTrans = 1; NbTrans <= 3; NbTrans++) {
            std::tuple<int, int, int> config = std::make_tuple(SF, TPdBm, NbTrans);
            auto it = PERpredic.find(config);
            if (it != PERpredic.end() && it->second <= PERtarget) {
                double ToA = calculateTimeOnAir(SF, payloadSize) * NbTrans;
                DEBUG_LOG("[CHECK] SF=" << SF << ", TPdBm=" << TPdBm << ", NbTrans=" << NbTrans
                             << ", ToA=" << ToA << ", PER=" << it->second);
                if (ToA < bestToA) {
                    bestToA = ToA;
                    bestConfig = config;
                    DEBUG_LOG("[INFO] New best config found.");
                }
            }
        }
    }
    
    DEBUG_LOG("[RESULT] Selected Config: SF=" << std::get<0>(bestConfig)
                 << ", TPdBm=" << std::get<1>(bestConfig)
                 << ", NbTrans=" << std::get<2>(bestConfig)
                 << " (ToA=" << bestToA << ")");
    DEBUG_LOG("===== [DEBUG END] chooseBestConfiguration =====\n");
    return bestConfig;
}


double NetworkServerApp::calculateTimeOnAir(int SF, int payloadBytes) {
    // Constants for LoRa
    double Tsym = pow(2, SF) / 125000.0; // Symbol period in seconds (BW=125kHz)
    int CodingRate = 4; // Default LoRaWAN CR 4/5
    
    // Calculate preamble time
    int preambleSymbols = 8; // Default
    double Tpreamble = (preambleSymbols + 4.25) * Tsym;
    
    // Calculate payload symbol count
    int H = 0; // 0 for explicit header, 1 for implicit
    int DE = (SF >= 11) ? 1 : 0; // Low data rate optimization
    int PL = payloadBytes;
    
    int payloadSymbols = 8 + std::max(ceil((8*PL - 4*SF + 28 + 16 - 20*H) / (4*(SF-2*DE))) * (CodingRate+4), 0.0);
    
    // Total time on air
    double Tpayload = payloadSymbols * Tsym;
    return Tpreamble + Tpayload;
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
