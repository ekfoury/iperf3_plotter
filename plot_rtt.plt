set terminal pdf
set output 'RTT.pdf'
set datafile separator " "

#set xdata time
#set timefmt "%H:%M:%S"
set xlabel "Time (sec)"
#set format x '%S'

#set autoscale

set ylabel "RTT"
#set format y "%s"
set yrange [0:*]; #set ytics(0,20,40,60,80,100,120,140,160,180,200,220,240,260,280,300)

set title "RTT over time"
set key reverse Left outside
set grid

set style data lines


FILES = system("ls -1 *.dat")
plot for [data in FILES] data u 2:8 with lines title data


#plot "flow_00.dat" using 2:5 title "Reno", \
#     "flow_01.dat" using 2:5 title "Cubic", \
#     "flow_02.dat" using 2:5 title "HTCP", \
#     "flow_03.dat" using 2:5 title "BBR", \

