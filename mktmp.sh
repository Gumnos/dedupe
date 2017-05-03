for base in . /tmp/dedupe
do
    rm -r ${base}/tmp 2>/dev/null
    mkdir -p ${base}/tmp/subdir
    for dir in tmp{,/subdir}
    do
        echo hello > ${base}/${dir}/a
        echo hello > ${base}/${dir}/b
        echo goodbye > ${base}/${dir}/c
    done
done
