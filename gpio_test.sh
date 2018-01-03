
path=/sys/class/gpio

#base=$(cat $path/gpiochip0/base)
#ngpio=$(cat $path/gpiochip0/ngpio)
#ngpio=$((ngpio-1))
#pin=$base
#while [ $pin -le $ngpio ]
#do
#    echo "$pin" > $path/export
#    echo out > $path/gpio$pin/direction
#    pin=$((pin+1))
#done

echo Opening GPIO for LEDs...
echo 15 > $path/export
echo 16 > $path/export
echo out > $path/gpio15/direction
echo out > $path/gpio16/direction

c=1
v=0
loops=20
usdelay=250000

echo Flashing LEDs...
while [ $c -le $loops ]
do
    if [ $v -eq 0 ]
    then
        v=1
    else
        v=0
    fi

    c=$((c+1))

    echo $v > $path/gpio15/value
    echo $v > $path/gpio16/value

    usleep $usdelay
done

echo Cleaning GPIOs...
echo 15 > $v/unexport
echo 16 > $v/unexport

echo Done.
