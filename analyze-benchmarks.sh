#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

rm -f /tmp/models-analyzed
touch /tmp/models-analyzed

for model in $(find . -name "*.tflite") ; do
	# get the modelname minus the fp16/fp32 portion
	modelname="$(basename ${model} .tflite | awk 'BEGIN{FS=OFS="_"}{NF--; print}')"
	modelprecision="$(basename ${model} .tflite | awk -F_ '{print $NF}')"

	if grep -q ${modelname} /tmp/models-analyzed ; then continue ; fi

	echo "${modelname} results in miliseconds:"
	for precision in fp32 fp16 ; do
		for delegate in cpu gpu ; do
			logfile="$(find . -name ${modelname}_${precision}.tflite-${delegate}-log.txt)"
			if [ -e "${logfile}" ] ; then
				echo -n "	${delegate} ${precision}: " ; grep timings ${logfile} | awk -F: '{print "scale=2 ; "$7+0" / 1000"}' | bc
			else
				echo "	${delegate} ${precision}: no results"
			fi
		done
	done
	echo ${modelname} >> /tmp/models-analyzed
	echo
done

rm -f /tmp/models-analyzed

