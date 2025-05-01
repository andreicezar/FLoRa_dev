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
        // Static parameters from .ini
        preambleSymbols = par("preambleSymbols").intValue();
        headerEnabled = par("headerEnabled").boolValue();
        lowDataRateOptimization = par("lowDataRateOptimization").boolValue();
        defaultPayloadSize = par("defaultPayloadSize").intValue();

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

void NetworkServerApp::evaluateADR(Packet* pkt, L3Address pickedGateway, double SNIRinGW, double RSSIinGW)
{
    bool sendADR = false;
    bool sendADRAckRep = false;
    double SNRm;
    int nodeIndex;

    pkt->trimFront();
    auto frame = pkt->removeAtFront<LoRaMacFrame>();
    const auto &rcvAppPacket = pkt->peekAtFront<LoRaAppPacket>();

    BW = frame->getLoRaBW().get();
    CR = frame->getLoRaCR();
    payloadSize = pkt->getByteLength();

    // Check ADR acknowledgment request from end-device
    if (rcvAppPacket->getOptions().getADRACKReq()) {
        sendADRAckRep = true;
    }

    // Update SNR history for the node
    for (uint i = 0; i < knownNodes.size(); i++) {
        if (knownNodes[i].srcAddr == frame->getTransmitterAddress()) {
            knownNodes[i].adrListSNIR.push_back(SNIRinGW);
            knownNodes[i].historyAllSNIR->record(SNIRinGW);
            knownNodes[i].historyAllRSSI->record(RSSIinGW);
            knownNodes[i].receivedSeqNumber->record(frame->getSequenceNumber());
            if (knownNodes[i].adrListSNIR.size() == 20)
                knownNodes[i].adrListSNIR.pop_front();
            knownNodes[i].framesFromLastADRCommand++;

            // Decide if an ADR command should be sent (either periodic or upon ADR ACK request)
            if (knownNodes[i].framesFromLastADRCommand == 20 || sendADRAckRep) {
                nodeIndex = i;
                knownNodes[i].framesFromLastADRCommand = 0;
                sendADR = true;
                // Compute SNRm based on selected ADR method (max or average SNR)
                if (adrMethod == "ADRopt") {
                    double totalSNR = 0;
                    for (double v : knownNodes[i].adrListSNIR) {
                        totalSNR += v;
                    }
                    SNRm = totalSNR / knownNodes[i].adrListSNIR.size();
                } else if (adrMethod == "max") {
                    SNRm = *max_element(knownNodes[i].adrListSNIR.begin(), knownNodes[i].adrListSNIR.end());
                } else { // "avg" (default)
                    double totalSNR = 0;
                    for (double v : knownNodes[i].adrListSNIR) {
                        totalSNR += v;
                    }
                    SNRm = totalSNR / knownNodes[i].adrListSNIR.size();
                }
            }
        }
    }
        
    if (sendADR || sendADRAckRep) {
        auto mgmtPacket = makeShared<LoRaAppPacket>();
        mgmtPacket->setMsgType(TXCONFIG);

        if (sendADR) {
            // Determine link margin and required SNR for current SF
            std::map<int, double> SNR_thresholds = {{7,-7.5}, {8,-10}, {9,-12.5}, {10,-15}, {11,-17.5}, {12,-20}};
            int currentSF = frame->getLoRaSF();
            double requiredSNR = SNR_thresholds[currentSF];
            double SNRmargin = SNRm - requiredSNR - adrDeviceMargin;
            knownNodes[nodeIndex].calculatedSNRmargin->record(SNRmargin);

            if (adrMethod == "ADRopt") {
                EV_INFO << " ADR type is ADRopt" << EV_ENDL;
                // ADRopt: optimize SF, TX power, and NbTrans based on predicted PER
                int optimalSF = currentSF;
                int optimalNbTrans = 1;
                double optimalTxPower = math::mW2dBmW(frame->getLoRaTP()) + 30;  // current TX power in dBm

                // Estimate PER for each SF (assuming current NbTrans)
                // Define perForSF as a nested map explicitly
                std::map<int, std::map<int, double>> perForSF;
                for (int sf = 7; sf <= 12; sf++) {
                    // Compute FER using Rayleigh fading model
                    double estFER = 1.0 - exp(-pow(10, (SNR_thresholds.at(sf) - SNRm) / 10.0));

                    // Compute PER for each NbTrans value
                    for (int NbTrans : {1, 2, 3}) {
                        perForSF[sf][NbTrans] = pow(estFER, NbTrans);  // PER for given SF & NbTrans
                    }
                }

                // Compute current PER (requires implemented method)
                double PERcurrent = getCurrentPER(knownNodes[nodeIndex]);
                double PERtarget = PERmax;

                if (PERcurrent > PERmax) {
                    PERtarget = std::max(0.01, PERmax - (PERcurrent - PERmax));
                }

                // Select the most efficient (SF, NbTrans) that maintains PER <= PERmax
                bool sfFound = false;
                double minToA = std::numeric_limits<double>::max();
                for (int sf = 7; sf <= 12; sf++) {
                    for (int NbTrans : {1, 2, 3}) {
                        if (perForSF[sf][NbTrans] < PERtarget) {
                            double ToA = computeTimeOnAir(sf, NbTrans);
                            if (ToA < minToA) {
                                optimalSF = sf;
                                optimalNbTrans = NbTrans;
                                minToA = ToA;
                            }
                        }
                    }
                }

                // If no SF/NbTrans combination meets PERmax, choose most robust SF12 with max repetitions
                if (!sfFound) {
                    optimalSF = 12;
                    optimalNbTrans = 3;
                }

                // Adjust repetition count (NbTrans) based on predicted PER at optimal SF
                if (perForSF[optimalSF][optimalNbTrans] > PERmax) {
                    optimalNbTrans = std::min(3, optimalNbTrans + 1);
                } else if (perForSF[optimalSF][optimalNbTrans] < 0.05) {
                    optimalNbTrans = std::max(1, optimalNbTrans - 1);
                }

                // Adjust TX power in 3 dB steps if excess or insufficient SNR margin
                int Nstep = round(SNRmargin / 3);
                while (Nstep > 0 && optimalTxPower > 2) {
                    optimalTxPower -= 3;
                    if (optimalTxPower < 2) {
                        optimalTxPower = 2;
                        break;
                    }
                    Nstep--;
                }
                while (Nstep < 0 && optimalTxPower < 14) {
                    optimalTxPower += 3;
                    if (optimalTxPower > 14) {
                        optimalTxPower = 14;
                        break;
                    }
                    Nstep++;
                }

                if (optimalSF < 7 || optimalSF > 12) {
                    EV_ERROR << "Invalid SF selected: " << optimalSF << endl;
                    return;
                }
                // Apply new ADR parameters
                LoRaOptions newOptions;
                newOptions.setLoRaSF(optimalSF);
                newOptions.setLoRaTP(optimalTxPower);
                EV << optimalSF << endl;
                EV << optimalTxPower << endl;
                mgmtPacket->setOptions(newOptions);

            } else {
                // Standard ADR (max/avg): adjust SF and TX power based on SNR margin
                int Nstep = round(SNRmargin / 3);
                int newSF = currentSF;
                double newTxPower = math::mW2dBmW(frame->getLoRaTP()) + 30;  // current TX power in dBm

                // Use available margin to increase data rate (lower SF)
                while (Nstep > 0 && newSF > 7) {
                    newSF--;
                    Nstep--;
                }
                // Use remaining margin to reduce TX power
                while (Nstep > 0 && newTxPower > 2) {
                    newTxPower -= 3;
                    Nstep--;
                }
                // If negative margin, increase TX power (up to max)
                while (Nstep < 0 && newTxPower < 14) {
                    newTxPower += 3;
                    Nstep++;
                }
                if (newTxPower > 14) newTxPower = 14;
                if (newTxPower < 2)  newTxPower = 2;

                LoRaOptions newOptions;
                newOptions.setLoRaSF(newSF);
                newOptions.setLoRaTP(newTxPower);
                EV << newSF << endl;
                EV << newTxPower << endl;
                mgmtPacket->setOptions(newOptions);
            }

            // Count ADR command for statistics (after warmup period)
            if (simTime() >= getSimulation()->getWarmupPeriod()) {
                knownNodes[nodeIndex].numberOfSentADRPackets++;
            }
        }

        // Send the ADR configuration (TXCONFIG) packet to the end-device via the gateway
        auto frameToSend = makeShared<LoRaMacFrame>();
        frameToSend->setChunkLength(B(par("headerLength").intValue()));
        frameToSend->setReceiverAddress(frame->getTransmitterAddress());
        frameToSend->setLoRaTP(math::dBmW2mW(14));  // set gateway TX power (14 dBm)
        frameToSend->setLoRaCF(frame->getLoRaCF());
        frameToSend->setLoRaSF(frame->getLoRaSF());
        frameToSend->setLoRaBW(frame->getLoRaBW());

        auto pktAux = new Packet("ADRPacket");
        mgmtPacket->setChunkLength(B(par("headerLength").intValue()));
        pktAux->insertAtFront(mgmtPacket);
        pktAux->insertAtFront(frameToSend);
        socket.sendTo(pktAux, pickedGateway, destPort);
    }
}

double NetworkServerApp::computeTimeOnAir(int SF, int NbTrans) {
    // Compute Symbol Duration
    double Tsymbol = pow(2, SF) / BW;

    // Compute Preamble Duration
    double Tpreamble = (preambleSymbols + 4.25) * Tsymbol;

    // Compute Payload Symbols
    int H = headerEnabled ? 0 : 1;  // Header presence (H)
    int D = lowDataRateOptimization ? 1 : 0;  // Low Data Rate Optimization (D)

    int payloadSymbols = 8 + std::max<int>(0, (int)ceil((8 * defaultPayloadSize - 4 * SF + 28 + 16 - 20 * H) /
                                      (4 * (SF - 2 * D))) * (CR + 4));


    // Compute Payload Duration
    double Tpayload = payloadSymbols * Tsymbol;

    // Compute Total ToA for one transmission
    double Ttotal = Tpreamble + Tpayload;

    // Multiply by NbTrans (number of repetitions)
    return Ttotal * NbTrans * 1000;  // Convert to milliseconds
}

double NetworkServerApp::getCurrentPER(const knownNode& node)
{
    int expectedFrames = 20; // the ADR window size

    int receivedFrames = node.adrListSNIR.size();
    int lostFrames = 20 - receivedFrames;

    // Ensure PER is between 0 and 1
    double PERcurrent = lostFrames / 20.0;

    return PERcurrent;
}


void NetworkServerApp::receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details)
{
    if (simTime() >= getSimulation()->getWarmupPeriod())
    {
        counterOfSentPacketsFromNodes++;
        counterOfSentPacketsFromNodesPerSF[value-7]++;
    }
}

} //namespace inet
