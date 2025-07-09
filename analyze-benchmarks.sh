#!/bin/bash

rm -f /tmp/models-analyzed
touch /tmp/models-analyzed

for model in $(find . -name "*.tflite") ; do
	# get the modelname minus the fp16/fp32 portion
	modelname="$(basename ${model} .tflite | awk 'BEGIN{FS=OFS="_"}{NF--; print}')"
	modelprecision="$(basename ${model} .tflite | awk -F_ '{print $NF}')"

	if grep -q ${modelname} /tmp/models-analyzed ; then continue ; fi

	echo "${modelname} results in microseconds:"
	for delegate in cpu gpu ; do
		for precision in fp32 fp16 ; do
			logfile="$(find . -name ${modelname}_${precision}.tflite-${delegate}-log.txt)"
			if [ -e "${logfile}" ] ; then
				echo -n "	${delegate} ${precision}: " ; grep timings ${logfile} | awk -F: '{print $7}'
			else
				echo "	${delegate} ${precision}: no results"
			fi
		done
	done
	echo ${modelname} >> /tmp/models-analyzed
	echo
done

rm -f /tmp/models-analyzed
