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
from os.path import isfile, join

SER = None
TFTP_SERVER = None
SER_BAUD = 115200
NUM_OF_THREADS = 0
SYSTEM_STOP = False
IN_MSGS = []
OUT_MSGS = []
MSG_LOCK = threading.Lock()
SER_LOCK = threading.Lock()

TFTP_DIR = './'
IMAGE_NAME = 'openwrt-ar71xx-generic-lima-squashfs-sysupgrade.bin'

def signal_handler(signal, frame):
    global SYSTEM_STOP
    global TFTP_SERVER
    print('\n\nExiting program...\n\n')
    SYSTEM_STOP = True
    if TFTP_SERVER is not None:
        TFTP_SERVER.stop()

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
        print (i+1), '-', ports[i]

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
    
    print 'You entered', selection, ',', ports[integer]

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

    state = 'none'
    board_ip = None
    server_ip = None
    prog = re.compile('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')

    while not SYSTEM_STOP:
        MSG_LOCK.acquire()
        if len(IN_MSGS) > 0:
            msg = IN_MSGS.pop(0)
            if state == 'none':
                if 'Hit \'<ESC>\' key(s) to stop autoboot:' in msg:
                    print 'Hit bootloader...'
                    OUT_MSGS.append('\x1b')
                if 'ath>' in msg:
                    print 'Successfully entered bootloader.'
                    state = 'bootloader'
                    OUT_MSGS.append('printenv\n')
            if state == 'bootloader':
                if 'ipaddr' in msg:
                    print msg
                    board_ip = prog.findall(msg)[0]
                    print 'IP:', board_ip
                if 'serverip' in msg:
                    print msg
                    server_ip = prog.findall(msg)[0]
                    print 'TFTP location:', server_ip
                

        MSG_LOCK.release()

    print 'Leaving process_thread.'


def tftp_thread():
    global SYSTEM_STOP
    global TFTP_SERVER

    tftp_dir = './'
    socket_timeout = 1
    
    try:
        TFTP_SERVER = tftpy.TftpServer(tftp_dir)
    except tftpy.TftpException:
        print 'Could not create TFTP server.'
        SYSTEM_STOP = True
        return

    print 'TFTP server started; serving from:', tftp_dir
    onlyfiles = [f for f in listdir(tftp_dir) if isfile(join(tftp_dir, f))]
    print 'Has files:\n\t-', '\n\t- '.join(onlyfiles)

    if IMAGE_NAME not in onlyfiles:
        print 'TFTP directory does not have the required firmware image!'
        return

    try:
        TFTP_SERVER.listen('0.0.0.0', 69, socket_timeout)
    except tftpy.TftpException, err:
        sys.stderr.write("%s\n" % str(err))
        sys.exit(1)
    except KeyboardInterrupt:
        pass

    time.sleep(0.1)
    print 'Leaving tftp_thread.'



if __name__ == '__main__':
    global SYSTEM_STOP

    base_threads = threading.active_count()
    signal.signal(signal.SIGINT, signal_handler)

    print 'Dookickey!'
    open_serial()

    print 'Starting threads... you can now power-on the Node.'

    threads = []
    threads.append(threading.Thread(target = serial_thread, args = ()))
    threads.append(threading.Thread(target = process_thread, args = ()))
    threads.append(threading.Thread(target = tftp_thread, args = ()))

    for thread in threads:
        thread.daemon = True
        thread.start()
        NUM_OF_THREADS += 1

    while threading.active_count() > base_threads:
        time.sleep(0.5)
        additional_threads = threading.active_count() - base_threads
        if additional_threads < NUM_OF_THREADS:
            SYSTEM_STOP = True
            print 'Waiting for close of ', additional_threads, '/', NUM_OF_THREADS, ' threads.'

    close_serial();

    sys.exit()








