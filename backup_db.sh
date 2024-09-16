# MAILTO=
# SHELL=/bin/bash
TS_LABEL=$(date +%FT%s)
PATH=/bin:/usr/bin:/usr/local/sbin:/usr/sbin:/sbin:/opt/aws/bin:$HOME/.local/bin:$HOME/bin:$PATH:/usr/local/bin
# DATA_DIR="$(psql  -U postgres postgres -0 -z -q  -t  -c 'show data_directory;'|tr -d ' ')"
OUTPUT=pmspp_${TS_LABEL}.sql.xz
LIME_OUTPUT=lime_${TS_LABEL}.sql.xz

sudo bash -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
find ./archive -mmin +200 -name pmspp_\*.sql.xz -exec rm -f {} \;
pg_dump -U postgres pmspp | xz -z -3 -c - >./backup/${OUTPUT}
mv ./backup/${OUTPUT} ./archive/
# pg_dump -U postgres lime | xz -z -3 -c - >./backup/${LIME_OUTPUT}
# mv ./backup/${LIME_OUTPUT} ./archive/

# SEE: https://www.vultr.com/docs/how-to-use-s3cmd-with-vultr-object-storage
if which s3cmd && [ -f $HOME/.s3cfg ] ; then
    s3cmd put ./archive/${OUTPUT} s3://pmspp-archive/${OUTPUT}
    # s3cmd put ./archive/${LIME_OUTPUT} s3://pmspp-archive/${LIME_OUTPUT}
fi
