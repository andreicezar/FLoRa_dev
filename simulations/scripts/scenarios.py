class ScenarioMetrics:
    def __init__(self, name):
        self.name = name

        self.analyzer_ref = None  # Reference to the LoRaSimulationAnalyzer instance
        # Core performance metrics
        self.pdr_map = {}
        self.per_map = {}
        self.der_per_node = {}
        self.data_extraction_rate_per_gateway = {}  # 👈 Add this line
        self.energy_per_delivered = {}
        self.toa_map = {}
        self.sf_map = {}
        self.rssi_map = {}
        self.tp_map = {}
        self.jain_index = None
        self.throughput = None
        self.packet_sent_map = {}
        self.collision_count_map = {}
        self.adr_command_count_map = {}
        self.retransmission_count_map = {}
        self.queue_overflow_drops = {}
        self.data_error_rate_map = {}
        # Signal quality
        self.snr_map = {}
        self.snir_map = {}

        # Raw vectors for detailed analysis
        self.tp_vectors = []      # Transmission Power over time
        self.sf_vectors = []      # Spreading Factor over time
        self.snir_vectors = []    # SNIR over time
        self.rssi_vectors = []    # RSSI over time
        self.snr_margin_vectors = [] #  SNR Margin over time

    def to_dict(self):
        return self.__dict__
