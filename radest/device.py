import socket, re
from .logger import globalLogger
# from logger import globalLogger # for Python MWE

class RadestDevice:
    def __init__(self, ip_address, port):
        self.socket = None
        self.ip = ip_address
        self.port = port
        self.meas_power = None
        self.b_recording = False
        self.command_list = []

    def connect(self):
        """
                connect to RadestDevice
        """
        globalLogger.info(self.ip)
        globalLogger.info(self.port)
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(1)
            self.socket.connect((self.ip, self.port))
            self.identify()
            self.sleep(0)
            self.socket.settimeout(300)
            return True

        except socket.error as error:
            globalLogger.info("Error connecting to RadestDevice:", error)
            return False

    def recv(self, buffer_size=64):
        full_msg = ''
        try:
            while True:
                msg = self.socket.recv(buffer_size)
                if len(msg) <= 0:
                    break

                full_msg += msg.decode("utf-8")

                if len(msg) < buffer_size:
                    break
        except:
            return "timeout"
        return full_msg

    def send(self, msg):

        self.socket.sendall(f'{msg:s}\0'.encode('utf-8'))
        globalLogger.info(f"Sending: {msg:s}")        

    def disconnect(self):
        try:
            globalLogger.info('Disconnecting..\n')
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            return True
        except Exception as e:
            globalLogger.warning("Error disconnecting: ", e)

        return False

     # Send and receive
    def send_scpi_and_print_answer(self, scpi_command):
        if self.b_recording:
            self.command_list.append(scpi_command)
        self.send(scpi_command)
        answer = self.recv().rstrip()
        globalLogger.info(f"receiving: {answer}")
        return answer

    def parse_numbers_from_string(self,s):
        try:
            return [float(x.strip()) for x in s.split(',')]
        except ValueError:
            raise ValueError("Invalid input string. Expected a comma-separated list of numbers.")
#####################################################################################################################
#####################################################################################################################

    ## REGION WITH SCPI COMMANDS
    
    def identify(self):
        scpi_command = "*IDN?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def sleep(self, on):
        scpi_command = f"SYSTEM:SLEEP {int(on)}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    def show_lan_mac_address(self):
        scpi_command = f"SHOW:LAN:MAC:ADDRESS?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    # ASDL Settings
    def asdl_enable(self):
        scpi_command = f"SYSTEM:ASDL:ENABLE"
        self.send_scpi_and_print_answer(scpi_command)

    def asdl_disable(self):
        scpi_command = f"SYSTEM:ASDL:DISABLE"
        self.send_scpi_and_print_answer(scpi_command)

    def target_set_distance(self, distance_in_m):
        scpi_command = f"TARGET:SET:DISTANCE {distance_in_m}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def target_get_distance(self):
        scpi_command = f"TARGET:GET:DISTANCE?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)  
        return round(float(value[0]), 2)

    def target_get_velocity(self):
        scpi_command = f"TARGET:GET:VELOCITY?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return int(answer)

    def target_set(self, distance_in_m, velocity_in_kmh, rx_antenna, tx_antenna):
        scpi_command = f"TARGET:SET {distance_in_m},{velocity_in_kmh},{rx_antenna},{tx_antenna}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Set system polarization
    def system_set_polarization_77ghz(self, polString):
        scpi_command = f"SYSTEM:SET:POLARIZATION:77GHZ:{polString}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Set 24 GHz system polarization
    def system_set_polarization_24ghz(self, polString):
        scpi_command = f"SYSTEM:SET:POLARIZATION:24GHz:{polString}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Get system polarization
    def system_get_polarization_77ghz_setting(self):
        scpi_command = f"SYSTEM:GET:POLARIZATION:77GHZ:SETTING?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Get 24 GHz system polarization
    def system_get_polarization_24ghz_setting(self):
        scpi_command = f"SYSTEM:GET:POLARIZATION:24GHz:SETTING?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Run polarization detection
    def measure_get_polarization_77ghz(self):
        scpi_command = f"MEASURE:GET:POLARIZATION?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    # Run freq. range detection
    def measure_get_frequencyrange(self):
        scpi_command = f"MEASURE:GET:FREQUENCYRANGE?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return self.parse_numbers_from_string(answer)
    
    # Save user settings to device
    def system_write_settings(self):
        scpi_command = f"SYSTEM:WRITE:SETTINGS"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def system_set_ref_ext(self):
        scpi_command = f"SYSTEM:SET:REF:EXT"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    def system_set_ref_int(self):
        scpi_command = f"SYSTEM:SET:REF:INT"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def system_get_ref(self):
        scpi_command = f"SYSTEM:GET:REF?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        answer = answer.strip('"')
        return answer
    
    # Extension enable/disable
    def extension_enable(self):
        scpi_command = "SYSTEM:EXTENSION:ENABLE"
        self.send_scpi_and_print_answer(scpi_command)

    def extension_disable(self):
        scpi_command = "SYSTEM:EXTENSION:DISABLE"
        self.send_scpi_and_print_answer(scpi_command)

    # Velocity Settings
    def set_velocity_to_value(self, velocity_in_km_h, b_towards):
        if b_towards:
            towards_away = "TOWARDS"
        else:
            towards_away = "AWAY"
        scpi_command = f"TARGET:SET:VELOCITY:{towards_away} {velocity_in_km_h}"
        self.send_scpi_and_print_answer(scpi_command)

    # Select Tx Antenna
    def system_set_tx(self, antenna_number):
        # antenna_number between 1 and 12
        scpi_command = f"SYSTEM:SET:TX {antenna_number}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Get Tx Antenna
    def system_get_tx(self):
        # antenna_number between 1 and 12
        scpi_command = f"SYSTEM:GET:TX?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return int(answer)

    # Select Rx Antenna
    def system_set_rx(self, antenna_number):
        # antenna_number between 1 and 12
        scpi_command = f"SYSTEM:SET:RX {antenna_number}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    # Get Rx Antenna
    def system_get_rx(self):
        # antenna_number between 1 and 12
        scpi_command = f"SYSTEM:GET:RX?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return int(answer)

    # Attenuation
    def system_set_attenuation(self, attenuation):
        scpi_command = f"SYSTEM:SET:ATTENUATION {attenuation}"
        self.send_scpi_and_print_answer(scpi_command)

    # Attenuation
    def system_get_attenuation(self):
        scpi_command = f"SYSTEM:GET:ATTENUATION?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return float(answer)
    
    # Target RCS
    def target_get_rcs_limits(self):
        scpi_command = f"TARGET:GET:RCS:LIMITS?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def target_set_rcs(self, rcs):
        scpi_command = f"TARGET:SET:RCS {rcs}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Scenario RCS
    def scenario_get_rcs_limits(self):
        scpi_command = f"SCENARIO:RCS:LIMITS?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    def scenario_set_rcs(self, rcs):
        scpi_command = f"SCENARIO:RCS {rcs}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def scenario_constant_rcs(self, constant_rcs):
        # Laut RadEsT-Handbuch: 0 = konstante RCS, 1 = variable RCS
        scpi_command = f"SCENARIO:RCS:CONST {constant_rcs}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    # Antenna group
    def system_set_ant_group(self,position,index):
        scpi_command = f"SYSTEM:SET:ANT:GROUP:{position} {index}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    # Scenario  
    def scenario_trigger(self):
        scpi_command = "SCENARIO:TRIGGER"
        self.send_scpi_and_print_answer(scpi_command)
        globalLogger.info("Scenario done")

    def scenario_distance_start(self, start_distance):
        scpi_command = f"SCENARIO:DISTANCE:START {start_distance}"
        self.send_scpi_and_print_answer(scpi_command)

    def scenario_get_distance_start(self):
        scpi_command = f"SCENARIO:DISTANCE:START?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)  
        return round(float(value[0]), 2)

    def scenario_distance_end(self, stop_distance):
        scpi_command = f"SCENARIO:DISTANCE:END {stop_distance}"
        self.send_scpi_and_print_answer(scpi_command)

    def scenario_get_distance_end(self):
        scpi_command = f"SCENARIO:DISTANCE:END?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)  
        return round(float(value[0]), 2)
    
    def scenario_velocity(self, velocity):
        if float(velocity) < 0:
            globalLogger.info("Setting scenario velocity impossible. Please provide velocity value > 0!")
            return
        scpi_command = f"SCENARIO:VELOCITY {velocity}"
        self.send_scpi_and_print_answer(scpi_command)

    def scenario_get_velocity(self):
        scpi_command = f"SCENARIO:VELOCITY?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return float(answer)

    # Power Measurement 77 GHz
    def measure_get_77ghz(self, rx_antenna = 0):
        scpi_command = f"MEASURE:GET:77GHZ? {rx_antenna}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_power = round(float(value[0]), 2)     
        return self.meas_power  

    # Power Measurement 24 GHz
    def measure_get_24ghz(self):
        scpi_command = "MEASURE:GET:24GHZ?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_power = round(float(value[0]), 2)     
        return self.meas_power  
        
    # 77 GHz EIRP Measurement
    def measure_get_77ghz_eirp(self, bp_tp_switch = 0): # 0=TP
        scpi_command = f"MEASURE:GET:77GHZ:EIRP? {bp_tp_switch}" 
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_power = round(float(value[0]), 2)   
        return self.meas_power
    
    # 24 GHz EIRP Measurement
    def measure_get_24ghz_eirp(self):
        scpi_command = f"MEASURE:GET:24GHz:EIRP?" 
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_power = round(float(value[0]), 2)   
        return self.meas_power
        
    # Normalization Measurement
    def start_norm_measurement(self, rx_antenna = 0):
        scpi_command = f"MEASURE:SET:NORMVALUE {rx_antenna}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        
    # NormEIRP Measurement
    def start_normEIRP_measurement(self, rx_antenna = 0):
        scpi_command = f"MEASURE:GET:NORMEIRP? {rx_antenna}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_power = round(float(value[0]), 2) 
        return self.meas_power     
            
    # Temperature Measurement
    def start_temperature_measurement_detector(self):
        scpi_command = "MEASURE:GET:RXDETTEMP?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        value = re.findall(r"[-+]?\d+\.\d+", answer)
        self.meas_temp = round(float(value[0]), 2)   
        return self.meas_temp 
        
    # Set Measurement Distance
    def set_airgap_distance(self, distance):
        scpi_command = f"SYSTEM:SET:AIRGAP {distance}"
        answer = self.send_scpi_and_print_answer(scpi_command)
            
    # Get Measurement Distance
    def get_airgap_distance(self):
        scpi_command = f"SYSTEM:GET:AIRGAP?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return round(float(answer), 2)

    # Set Measurement Frequency
    def system_set_centerfreq(self, frequency):
        scpi_command = f"SYSTEM:SET:CENTERFREQ {frequency}"
        answer = self.send_scpi_and_print_answer(scpi_command)
            
    # Get Measurement Frequency
    def system_get_centerfreq(self):
        scpi_command = f"SYSTEM:GET:CENTERFREQ?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return round(float(answer), 2)

    # Set Measurement Bandwidth
    def system_set_bandwidth(self, bandwidth):
        scpi_command = f"SYSTEM:SET:BANDWIDTH {bandwidth}"
        answer = self.send_scpi_and_print_answer(scpi_command)
            
    # Get Measurement Bandwidth
    def system_get_bandwidth(self):
        scpi_command = f"SYSTEM:GET:BANDWIDTH?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return round(float(answer), 2)
    
    # Set Measurement Interval
    def measure_set_interval(self, interval):
        scpi_command = f"MEASURE:SET:INTERVAL {interval}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        
    # Get Measurement Interval
    def measure_get_interval(self):
        scpi_command = f"MEASURE:GET:INTERVAL?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return int(answer)
    
    # Set Measurement Warmup
    def measure_set_warmup(self, interval):
        scpi_command = f"MEASURE:SET:WARMUP {interval}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        
    # Get Measurement Warmup
    def measure_get_warmup(self):
        scpi_command = f"MEASURE:GET:WARMUP?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return int(answer)
    
    def set_lan_ip(self, ip_address):
        scpi_command = f"SET:LAN:IP {ip_address}"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    def set_lan_init(self):
        scpi_command = f"SET:LAN:INIT"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer

    def system_preset(self):
        scpi_command = "SYSTEM:PRESET"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def system_preset_user(self):
        scpi_command = "SYSTEM:PRESET:USER"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    def show_lan_mac_address(self):
        scpi_command = "SHOW:LAN:MAC:ADDRESS?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
    
    # Perform self-test
    def system_selftest(self):
        scpi_command = "SYSTEM:SELFTEST?"
        answer = self.send_scpi_and_print_answer(scpi_command)
        return answer
