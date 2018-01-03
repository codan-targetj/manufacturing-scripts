#! /bin/sh

test_number=1

unexport_all_gpios()
{
    gpiopath=/sys/class/gpio
    base=$(cat $gpiopath/gpiochip0/base)
    ngpio=$(cat $gpiopath/gpiochip0/ngpio)
    ngpio=$((ngpio-1))
    pin=$base
    while [ $pin -le $ngpio ]
    do
        echo "$pin" > $gpiopath/unexport 2> /dev/null
        pin=$((pin+1))
    done
}

test()
{
	title=$1
	data=$2

	echo -e "Test $test_number - $title:\t\c"
	if [ $# -gt 2 ]
	then
		if [ X"$data" = X"$3" ]
		then
			echo PASS
		else
			echo FAIL
		fi
	else
		if [ X"$data" = X"" ]
		then
			echo FAIL
		else
			echo PASS
		fi
	fi
	test_number=$((test_number+1))
}


echo Preliminary setup for tests...
unexport_all_gpios

echo Beginning tests...

version=$(uname -r)
test "OpenWrt linux kernel version"	$version 4.1.23

test "SC16IS7xx driver is available"	$(ls /lib/modules/$version/ | grep sc16is7xx)
test "SC16IS7xx driver is loaded"	"$(lsmod | grep sc16is7xx)"
test "BMI160 driver is available"	$(ls /lib/modules/$version/ | grep bmi160)
test "BMI160 driver is loaded"		"$(lsmod | grep bmi160)"

test "Debug UART is available"		"$(ls /dev/ttyS0)"
test "Debug UART is 115200 baud"	"$(stty -a -F /dev/ttyS0 2> /dev/null | grep 115200)"

test "WASP UART is available"		"$(ls /dev/ttySC0)"
test "WASP UART is 230400 baud"		"$(stty -a -F /dev/ttySC0 2> /dev/null | grep 230400)"


test "GPIO chip 0 is available"		"$(ls /sys/class/gpio/gpiochip0)"
test "GPIO chip 56 is available"	"$(ls /sys/class/gpio/gpiochip56)"

echo 0 > /sys/class/gpio/export 2> /dev/null
test "GPIO_0 is NOT exportable"		$? 1
echo 1 > /sys/class/gpio/export 2> /dev/null
test "GPIO_1 is NOT exportable"		$? 1

echo 15 > /sys/class/gpio/export 2> /dev/null
test "GPIO_15 is exportable"		$? 0
echo 16 > /sys/class/gpio/export 2> /dev/null
test "GPIO_16 is exportable"		$? 0

test "GPIO_15 is writeable (HIGH)"	"$(echo out > /sys/class/gpio/gpio15/direction; echo 1 > /sys/class/gpio/gpio15/value; cat /sys/class/gpio/gpio15/value | grep 1)"
test "GPIO_15 is writeable (LOW)"	"$(echo out > /sys/class/gpio/gpio15/direction; echo 0 > /sys/class/gpio/gpio15/value; cat /sys/class/gpio/gpio15/value | grep 0)"

test "GPIO_16 is writeable (HIGH)"	"$(echo out > /sys/class/gpio/gpio16/direction; echo 1 > /sys/class/gpio/gpio16/value; cat /sys/class/gpio/gpio16/value | grep 1)"
test "GPIO_16 is writeable (LOW)"	"$(echo out > /sys/class/gpio/gpio16/direction; echo 0 > /sys/class/gpio/gpio16/value; cat /sys/class/gpio/gpio16/value | grep 0)"


echo Finished tests. Cleaning...
unexport_all_gpios