#! /usr/bin/env python

# Manufacturing SW install script.
# Ver 0.0.1.

import sys
import glob
import serial
import threading
import signal
import time
import tftpy
import re
from os import listdir
from os.path import isfile, join, getsize
import netifaces
import _winreg as wr

DEBUG = False
SER = None
TFTP_SERVER = None
SER_BAUD = 115200
NUM_OF_THREADS = 0
SYSTEM_STOP = False
IN_MSGS = []
OUT_MSGS = []
MSG_LOCK = threading.Lock()
SER_LOCK = threading.Lock()
IFACES = []
WAIT_FOR_PORTS_UP = 5
INADDR_ANY = ""
HR = '\n==================================================================\n'

TFTP_DIR = './'
IMAGE_NAME = 'openwrt-ar71xx-generic-lima-squashfs-sysupgrade.bin'
IMAGE_SIZE = 0

def signal_handler(signal, frame):
    global SYSTEM_STOP
    global TFTP_SERVER
    print '\n', HR, '\nExiting program...\n'
    SYSTEM_STOP = True
    if TFTP_SERVER is not None:
        TFTP_SERVER.stop()

def get_ip(iface):
    ip = None
    for k,v in netifaces.ifaddresses(iface).iteritems():
        for x in v:
            if "addr" in x:
                if x["addr"].find(".") != -1 and x["addr"].find(":") == -1:
                    if ip == None or int(ip.split('.')[0]) > int(x["addr"].split('.')[0]):
                        ip = x["addr"]
    return ip

def get_connection_name_from_guid(iface_guid):
   # Windows specific code to get meaningful names out of netifaces
    iface_name = '(unknown)'
    reg = wr.ConnectRegistry(None, wr.HKEY_LOCAL_MACHINE)
    reg_key = wr.OpenKey(reg, r'SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}')
    try:
        reg_subkey = wr.OpenKey(reg_key, iface_guid + r'\Connection')
        iface_name = wr.QueryValueEx(reg_subkey, 'Name')[0]
    except Exception as inst:
        pass

    return iface_name

def cat_serial_ports():
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

def open_serial():
    global SER
    print 'Available serial ports are:'

    ports = cat_serial_ports()
    for i in xrange(len(ports)):
        print '\t', (i+1), '-', ports[i]

    selection = raw_input('Enter a number to select a serial port: ')

    try:
        integer = int(selection)
    except ValueError:
        print 'Invalid input.'
        quit()

    integer = integer - 1
    if integer not in xrange(len(ports)):
        print 'Input does not correspond to an option given'
        quit()
    
    print 'You selected', selection, '(', ports[integer], ')'

    SER_LOCK.acquire()
    SER = serial.Serial(ports[integer], SER_BAUD, timeout=0.1)
    SER_LOCK.release()

def close_serial():
    global SER
    print 'Closing the serial connection...'
    SER_LOCK.acquire()
    SER.close()
    SER = None
    SER_LOCK.release()

def serial_thread():
    global SER
    global IN_MSGS
    global OUT_MSGS

    while not SYSTEM_STOP:
        # write messages
        SER_LOCK.acquire()
        MSG_LOCK.acquire()
        if len(OUT_MSGS) > 0:
            msg = OUT_MSGS.pop(0)
            if DEBUG:
                print 'Sending:', msg
            SER.write(msg)
        SER_LOCK.release()
        MSG_LOCK.release()
        
        # read messages
        line = None
        try:
            SER_LOCK.acquire()
            line = SER.readline()
            SER_LOCK.release()
        except serial.SerialTimeoutException:
            print('Data could not be read - timeout exception')

        if line is not None and len(line) != 0:
            MSG_LOCK.acquire()
            IN_MSGS.append(line)
            MSG_LOCK.release()
    
    print 'Leaving serial_thread.'


def process_thread():
    global IN_MSGS
    global OUT_MSGS
    global IMAGE_SIZE

    state = 'none'
    board_ip = None
    server_ip = None
    wrote_success = 0
    prog = re.compile('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    number = re.compile('\s\d+\s')

    while not SYSTEM_STOP:
        MSG_LOCK.acquire()
        if len(IN_MSGS) > 0:
            msg = IN_MSGS.pop(0)

            if state == 'none':
                state = 'unknown'

            if state != 'testboot':
                if '-------------------------------------' in msg:
                    state = 'unknown'
                    board_ip = None
                    server_ip = None
                    wrote_success = 0
                    print 'Detected new device on serial!'
                    del OUT_MSGS[:]
                if 'Uncompressing Kernel Image ...' in msg:
                    print 'Failed to enter bootloader. Please power-cycle the device.'
                    state = 'failed'
                
            if state == 'unknown':
                if 'Hit \'<ESC>\' key(s) to stop autoboot:' in msg:
                    print 'Hit bootloader...'
                    OUT_MSGS.append('\x1b')
                if 'ath>' in msg:
                    print '\tSuccessfully entered bootloader.'
                    state = 'bootloader'
                    OUT_MSGS.append('printenv\n')
                    
            elif state == 'bootloader':
                if 'ipaddr' in msg:
                    board_ip = prog.findall(msg)[0]
                if 'serverip' in msg:
                    server_ip = prog.findall(msg)[0]
                    
                if 'ath>' in msg:
                    print '\tIP:', board_ip
                    print '\tTFTP location:', server_ip
                    if server_ip in [x[2] for x in IFACES]:
                        print '\tTFTP requests will be made to this PC on interface:', IFACES[[x[2] for x in IFACES].index(server_ip)][1]
                        OUT_MSGS.append('tftpboot ')
                        OUT_MSGS.append('0x80060000 ')
                        OUT_MSGS.append(str(IMAGE_NAME))
                        OUT_MSGS.append('\n')
                        print 'Waiting for eth ports to become active...'
                        time_slept = 0
                        while time_slept < WAIT_FOR_PORTS_UP:
                            print '\t', int(WAIT_FOR_PORTS_UP - time_slept), '...'
                            time.sleep(1)
                            time_slept = time_slept + 1
                        
                        print 'Requesting new firmware over TFTP...'
                        state = 'tftp'
                    else:
                        print '\tDevice attempting to find TFTP server at unknown location!'
                        state = 'failed'
                        
            elif state == 'tftp':
                if 'Tx Timed out' in msg:
                    print '\tRequest timed out. Retrying...'
                if 'Retry count exceeeded' in msg:
                    print '\t', msg[:-1]
                if '#################################################################' in msg:
                    print '\tTransferring...'
                if 'Bytes transferred =' in msg:
                    bytes_tfer = int(number.findall(msg)[0])
                    print '\tTransferred', bytes_tfer, '/', IMAGE_SIZE, 'bytes'
                    if bytes_tfer != IMAGE_SIZE:
                        print '\tDid not transfer the complete image!'
                        state = 'failed'
                    else:
                        state = 'tferwaitath'
            
            elif state == 'tferwaitath':
                if 'ath>' in msg:
                    state = 'overwrite'
                    OUT_MSGS.append('sf erase 0xC0000 +${filesize};')
                    OUT_MSGS.append(' sf write 0x80060000 0xC0000 ${filesize}')
                    OUT_MSGS.append('\n')
                    print 'Overwriting flash...'
            elif state == 'overwrite':
                if 'Erased:' in msg:
                    if 'OK' in msg:
                        print '\tErasing flash completed successfully.'
                        wrote_success = wrote_success + 1
                    else:
                        print '\tFailed to erase old flash data'
                        state = 'failed'
                if 'Written:' in msg:
                    if 'OK' in msg:
                        print '\tWriting flash completed successfully.'
                        wrote_success = wrote_success + 1
                    else:
                        print '\tFailed to write new image to flash'
                        state = 'failed'
                if 'ath>' in msg:
                    if wrote_success == 2:
                        state = 'testboot'
                        OUT_MSGS.append('reset\n')
                        print 'Performing test reboot...'
                    else:
                        state = 'failed'
                    
            elif state == 'testboot':
                if '-------------------------------------' in msg:
                    print '\tTEST BOOT: Detected bootloader...'
                if 'Verifying Checksum' in msg:
                    print '\tTEST BOOT: Verifying checksum (data integrity)...'
                if 'Starting kernel ...' in msg:
                    print '\tTEST BOOT: Data intact. Starting OS...'
                if '[    0.000000] Linux version' in msg:
                    print '\tTEST BOOT: Kernel is booting correctly.'
                    print '\tWaiting to begin filesystem reconstruction...'
                if 'jffs2_build_filesystem(): erasing all blocks after the end marker...' in msg:
                    print '\tTEST BOOT: Reconstructing filesystem. DO NOT POWER OFF THE DEVICE. This may take 2 to 3 minutes.'
                if 'jffs2_build_xattr_subsystem: complete building xattr subsystem' in msg:
                    print '\tTEST BOOT: passed.\n'
                    state = 'none'

            if state == 'failed':
                print 'Firmware upload has failed. Please try again.'
                state = 'none'
            if state == 'none':
                print '\nYou can now connect and power-on a new Node.'
            if DEBUG:
                print state, ';MSG:', msg

        MSG_LOCK.release()

    print 'Leaving process_thread.'


def tftp_thread():
    global SYSTEM_STOP
    global TFTP_SERVER

    try:
        TFTP_SERVER.listen(INADDR_ANY, 69)
    except tftpy.TftpException, err:
        SYSTEM_STOP = True
        print str(err)
    except KeyboardInterrupt:
        pass

def start_tftp():
    global TFTP_SERVER
    global IMAGE_SIZE
    global NUM_OF_THREADS
    
    try:
        TFTP_SERVER = tftpy.TftpServer(TFTP_DIR)
    except tftpy.TftpException:
        print 'Could not create TFTP server.'
        SYSTEM_STOP = True
        return False

    print 'TFTP server started; serving from:', TFTP_DIR
    onlyfiles = [f for f in listdir(TFTP_DIR) if isfile(join(TFTP_DIR, f))]
    print 'Has files:\n\t-', '\n\t- '.join(onlyfiles)

    if IMAGE_NAME not in onlyfiles:
        print 'TFTP directory does not have the required firmware image!'
        return False
    else:
        IMAGE_SIZE = getsize(join(TFTP_DIR, f))
        print 'TFTP file to serve is', IMAGE_SIZE, 'bytes'
    
    tftp = threading.Thread(target = tftp_thread, args = ())
    tftp.daemon = True
    tftp.start()
    NUM_OF_THREADS += 1    

    return True


def clean_close():
    close_serial()
    sys.exit()

if __name__ == '__main__':
    base_threads = threading.active_count()
    signal.signal(signal.SIGINT, signal_handler)

    print '\nChecking interfaces...'
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        interface_name = get_connection_name_from_guid(interface)
        interface_ip = get_ip(interface)
        if interface_ip is not None:
            IFACES.append([interface, interface_name, interface_ip])
            print '\t-', interface_name, interface_ip

    print '\nStarting TFTP server...'
    if not start_tftp():
        clean_close()

    print '\nOpening serial device...'
    open_serial()
    
    print '\nStarting communication and processing threads...'
    threads = []
    threads.append(threading.Thread(target = serial_thread, args = ()))
    threads.append(threading.Thread(target = process_thread, args = ()))

    for thread in threads:
        thread.daemon = True
        thread.start()
        NUM_OF_THREADS += 1

    time.sleep(1)
    additional_threads = threading.active_count() - base_threads
    if additional_threads == NUM_OF_THREADS:
        print HR, '\nYou can now power-on the Node.'

    while threading.active_count() > base_threads:
        time.sleep(0.5)
        additional_threads = threading.active_count() - base_threads
        if additional_threads < NUM_OF_THREADS:
            SYSTEM_STOP = True
            print 'Waiting for close of ', additional_threads, '/', NUM_OF_THREADS, ' threads.'

    clean_close()








