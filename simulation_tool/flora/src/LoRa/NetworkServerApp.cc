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

#include "NetworkServerApp.h"
//#include "inet/networklayer/ipv4/IPv4Datagram.h"
//#include "inet/networklayer/contract/ipv4/IPv4ControlInfo.h"
#include "inet/networklayer/common/L3AddressTag_m.h"
#include "inet/transportlayer/common/L4PortTag_m.h"
#include "inet/transportlayer/contract/udp/UdpControlInfo_m.h"
#include "inet/networklayer/common/L3AddressResolver.h"
#include "inet/common/ModuleAccess.h"
#include "inet/applications/base/ApplicationPacket_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/SignalTag_m.h"
#include <cmath> // Required for log10()

#include "inet/networklayer/common/L3Tools.h"
#include "inet/networklayer/ipv4/Ipv4Header_m.h"

namespace flora {

Define_Module(NetworkServerApp);

double PERmax = 0.3;  // Maximum acceptable PER for FEC

void NetworkServerApp::initialize(int stage)
{

    if (stage == 0) {
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

    if(nodeExist == false)
    {
        knownNode newNode;
        newNode.srcAddr= frame->getTransmitterAddress();
        newNode.lastSeqNoProcessed = frame->getSequenceNumber();
        newNode.framesFromLastADRCommand = 0;
        newNode.numberOfSentADRPackets = 0;
        newNode.historyAllSNIR = new cOutVector;
        newNode.historyAllSNIR->setName("Vector of SNIR per node");
        //newNode.historyAllSNIR->record(pkt->getSNIR());
        newNode.historyAllSNIR->record(math::fraction2dB(frame->getSNIR()));
        newNode.historyAllRSSI = new cOutVector;
        newNode.historyAllRSSI->setName("Vector of RSSI per node");
        newNode.historyAllRSSI->record(frame->getRSSI());
        newNode.receivedSeqNumber = new cOutVector;
        newNode.receivedSeqNumber->setName("Received Sequence number");
        newNode.calculatedSNRmargin = new cOutVector;
        newNode.calculatedSNRmargin->setName("Calculated SNRmargin in ADR");
        knownNodes.push_back(newNode);
    }
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

void NetworkServerApp::evaluateADR(Packet* pkt, L3Address pickedGateway, double SNIRinGW, double RSSIinGW)
{
    bool sendADR = false;
    bool sendADRAckRep = false;
    double SNRm = 0;
    int nodeIndex = -1;

    pkt->trimFront();
    auto frame = pkt->removeAtFront<LoRaMacFrame>();
    const auto &rcvAppPacket = pkt->peekAtFront<LoRaAppPacket>();

    double BW = frame->getLoRaBW().get();
    int CR = frame->getLoRaCR();
    int payloadSize = pkt->getByteLength();    

    if (rcvAppPacket->getOptions().getADRACKReq()) {
        sendADRAckRep = true;
    }

    for (uint i = 0; i < knownNodes.size(); i++) {
        if (knownNodes[i].srcAddr == frame->getTransmitterAddress()) {
            int gwIndex = getGatewayIndexByAddress(pickedGateway);
            knownNodes[i].adrListSNIR.push_back({gwIndex, SNIRinGW});
            knownNodes[i].historyAllSNIR->record(SNIRinGW);
            knownNodes[i].historyAllRSSI->record(RSSIinGW);
            knownNodes[i].receivedSeqNumber->record(frame->getSequenceNumber());
            if (knownNodes[i].adrListSNIR.size() == 20)
                knownNodes[i].adrListSNIR.pop_front();
            knownNodes[i].framesFromLastADRCommand++;

            if (knownNodes[i].framesFromLastADRCommand == 20 || sendADRAckRep) {
                nodeIndex = i;
                knownNodes[i].framesFromLastADRCommand = 0;
                sendADR = true;

                if (adrMethod == "ADRopt" || adrMethod == "avg") {
                    double totalSNR = 0;
                    for (const auto& pair : knownNodes[i].adrListSNIR)
                        totalSNR += pair.second;
                    SNRm = totalSNR / knownNodes[i].adrListSNIR.size();
                } else if (adrMethod == "max") {
                    SNRm = std::max_element(knownNodes[i].adrListSNIR.begin(), knownNodes[i].adrListSNIR.end(),
                        [](const auto& a, const auto& b) {
                            return a.second < b.second;
                        })->second;
                }
            }
        }
    }

    int currentSF = frame->getLoRaSF();
    double optimalTxPower = math::mW2dBmW(frame->getLoRaTP()) + 30;
    int optimalSF = currentSF;
    if (nodeIndex != -1 && (sendADR || sendADRAckRep)) {
        auto mgmtPacket = makeShared<LoRaAppPacket>();
        mgmtPacket->setMsgType(TXCONFIG);

        if (sendADR) {
            std::map<int, double> SNR_thresholds = {{7,-7.5}, {8,-10}, {9,-12.5}, {10,-15}, {11,-17.5}, {12,-20}};
            double requiredSNR = SNR_thresholds[currentSF];
            double SNRmargin = SNRm - requiredSNR - adrDeviceMargin;
            knownNodes[nodeIndex].calculatedSNRmargin->record(SNRmargin);

            if (adrMethod == "ADRopt") {
                EV_INFO << " ADR type is ADRopt" << EV_ENDL;
                int optimalNbTrans = 1;

                double PERcurrent = getCurrentPER(knownNodes[nodeIndex]);
                double PERtarget = (PERcurrent > PERmax) ?
                    std::max(0.01, PERmax - (PERcurrent - PERmax)) : PERmax;

                std::map<int, std::map<int, double>> perPredictions;
                bool validConfigFound = false;
                double minToA = std::numeric_limits<double>::max();
                std::vector<int> receptionGWs = getReceptionGateways(knownNodes[nodeIndex]);

                for (int sf = 7; sf <= 12; sf++) {
                    for (int nbTrans = 1; nbTrans <= 3; nbTrans++) {
                        double combinedFER = 1.0;

                        for (int gwId : receptionGWs) {
                            double maxSNR = getMaxSNR(knownNodes[nodeIndex], gwId);
                            double sizeS = 20.0 / (1.0 - PERcurrent) * knownNodes[nodeIndex].lastNbTrans;

                            double SNRapproxMax = (
                                10.0 * log10(inverseCDFexp(0.95 * (1.0 / sizeS))) +
                                10.0 * log10(inverseCDFexp(0.05 * (1.0 / sizeS)))
                            ) / 2.0;

                            double SNRhat = maxSNR - SNRapproxMax;
                            double SNRfloor = -20.0 + ((12 - sf) * 2.5);

                            double FER = 1.0 - exp(-pow(10.0, (SNRfloor - SNRhat) / 10.0));

                            // Înlocuim: perPredictions[sf][nbTrans] *= pow(FER, nbTrans);
                            // cu:
                            combinedFER *= FER;
                        }

                        perPredictions[sf][nbTrans] = pow(combinedFER, nbTrans);
                    }
                }

                for (int sf = 7; sf <= 12; sf++) {
                    for (int nbTrans = 1; nbTrans <= 3; nbTrans++) {
                        if (perPredictions[sf][nbTrans] <= PERtarget) {
                            double ToA = computeTimeOnAir(sf, nbTrans);
                            if (ToA < minToA) {
                                optimalSF = sf;
                                optimalNbTrans = nbTrans;
                                minToA = ToA;
                                validConfigFound = true;
                            }
                        }
                    }
                }

                if (!validConfigFound) {
                    optimalSF = 12;
                    optimalNbTrans = 3;
                }
                knownNodes[nodeIndex].lastNbTrans = optimalNbTrans;

                int Nstep = round(SNRmargin / 3);
                while (Nstep > 0 && optimalTxPower > 2) {
                    optimalTxPower -= 3;
                    Nstep--;
                }
                while (Nstep < 0 && optimalTxPower < 14) {
                    optimalTxPower += 3;
                    Nstep++;
                }

                LoRaOptions newOptions;
                newOptions.setLoRaSF(optimalSF);
                newOptions.setLoRaTP(std::clamp(optimalTxPower, 2.0, 14.0));
                EV << "Selected SF: " << optimalSF << endl;
                EV << "Selected TX Power: " << optimalTxPower << endl;
                EV << "Selected NbTrans: " << optimalNbTrans << endl;
                mgmtPacket->setOptions(newOptions);
            } else {
                int Nstep = round(SNRmargin / 3);

                while (Nstep > 0 && optimalSF > 7) { optimalSF--; Nstep--; }
                while (Nstep > 0 && optimalTxPower > 2) { optimalTxPower -= 3; Nstep--; }
                while (Nstep < 0 && optimalTxPower < 14) { optimalTxPower += 3; Nstep++; }

                LoRaOptions newOptions;
                newOptions.setLoRaSF(optimalSF);
                newOptions.setLoRaTP(std::clamp(optimalTxPower, 2.0, 14.0));
                EV << optimalSF << endl;
                EV << optimalTxPower << endl;
                mgmtPacket->setOptions(newOptions);
            }

            if (simTime() >= getSimulation()->getWarmupPeriod()) {
                knownNodes[nodeIndex].numberOfSentADRPackets++;
            }
        }

        auto frameToSend = makeShared<LoRaMacFrame>();
        frameToSend->setChunkLength(B(par("headerLength").intValue()));
        frameToSend->setReceiverAddress(frame->getTransmitterAddress());
        // vechi:
        // frameToSend->setLoRaSF(frame->getLoRaSF());  // ❌ păstrează vechiul SF
        // frameToSend->setLoRaTP(math::dBmW2mW(14));   // ❌ hardcodat

        frameToSend->setLoRaSF(optimalSF);
        frameToSend->setLoRaTP(math::dBmW2mW(optimalTxPower));
        frameToSend->setLoRaCF(frame->getLoRaCF());
        frameToSend->setLoRaBW(frame->getLoRaBW());

        auto pktAux = new Packet("ADRPacket");
        mgmtPacket->setChunkLength(B(par("headerLength").intValue()));
        pktAux->insertAtFront(mgmtPacket);
        pktAux->insertAtFront(frameToSend);
        socket.sendTo(pktAux, pickedGateway, destPort);
    }
}

double NetworkServerApp::getCurrentPER(const knownNode& node)
{
    int receivedFrames = node.adrListSNIR.size(); // Number of frames in history (max 20)
    
    // Get the current NbTrans value from the node
    int nbTrans = node.lastNbTrans;  // ✔️ Correct

    
    // Total expected frames considering frame repetitions
    // In ADR_opt, the actual size of sample S should be: 20 / (1 - PER_current) × Nb_Trans
    // We need to solve for PER_current:
    // If we received 20 frames and NbTrans = 1, PER = 0
    // If we received 20 frames and NbTrans = 2, some frames were lost
    
    // Theoretical maximum number of unique frames that could have been received
    double theoreticalFrames = receivedFrames / static_cast<double>(nbTrans);
    
    // The ADR history window size is 20 frames
    const int historyWindowSize = 20;
    
    // PER calculation: (expected - received) / expected
    double PERcurrent = (historyWindowSize - theoreticalFrames) / historyWindowSize;
    
    // Ensure PER is between 0 and 1
    PERcurrent = std::max(0.0, std::min(1.0, PERcurrent));
    
    return PERcurrent;
}

int NetworkServerApp::getGatewayIndexByAddress(const L3Address& addr) {
    for (size_t i = 0; i < knownGateways.size(); i++) {
        if (knownGateways[i].ipAddr == addr)
            return i;
    }
    return -1; // Not found
}

double NetworkServerApp::computeTimeOnAir(int sf, int nbTrans) {
    // This is a rough Time-on-Air estimate, customize as needed
    double BW = 125000.0;  // LoRa bandwidth (e.g., 125 kHz)
    int payloadSize = 10;  // Adjust to your actual payload
    int CR = 1;            // Coding rate denominator (e.g., CR=4/5 -> CR = 1)

    double Tsym = pow(2, sf) / BW;
    double Tpreamble = (8 + 4.25) * Tsym;
    double DE = (sf >= 11) ? 1 : 0;
    double H = 0;  // Implicit header disabled
    double payloadSymbNb = 8 + std::max(
        std::ceil((8.0 * payloadSize - 4.0 * sf + 28 + 16 - 20 * H)
                  / (4.0 * (sf - 2 * DE))) * (CR + 4), 0.0);

    double Tpayload = payloadSymbNb * Tsym;
    return nbTrans * (Tpreamble + Tpayload);  // Account for NbTrans
}

// Helper function to compute inverse of exponential CDF
double NetworkServerApp::inverseCDFexp(double p) {
    // For exponential distribution with mean 1, inverse CDF is -log(1-p)
    return -log(1.0 - p);
}

// Function to get list of gateways that have received messages from this node
std::vector<int> NetworkServerApp::getReceptionGateways(const knownNode& node) {
    std::vector<int> gwIds;
    std::set<int> uniqueGwIds;
    
    // Iterate through the node's history and collect unique gateway IDs
    for (const auto& entry : node.adrListSNIR) {
        int gwId = entry.first;  // Assuming this is where the gateway ID is stored
        if (uniqueGwIds.find(gwId) == uniqueGwIds.end()) {
            uniqueGwIds.insert(gwId);
            gwIds.push_back(gwId);
        }
    }
    
    return gwIds;
}

// Function to get maximum SNR for a given node and gateway
double NetworkServerApp::getMaxSNR(const knownNode& node, int gwId) {
    double maxSNR = -std::numeric_limits<double>::infinity();
    
    // Iterate through the node's history and find max SNR for the specified gateway
    for (const auto& entry : node.adrListSNIR) {
        if (entry.first == gwId) {
            double snr = entry.second;        
            maxSNR = std::max(maxSNR, snr);
        }
    }
    
    return maxSNR;
}

} //namespace inet
