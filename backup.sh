#!/usr/bin/env bash
MAILTO=nad2000@gmail.com
# SHELL=/bin/bash
TS_LABEL=$(date +%FT%H%M%S)
PATH=/bin:/usr/bin:/usr/local/sbin:/usr/sbin:/sbin:/opt/aws/bin:$HOME/.local/bin:$HOME/bin:$PATH:/usr/local/bin
DATA_DIR="$(psql  -U postgres postgres -0 -z -q  -t  -c 'show data_directory;'|tr -d ' ')"
BUCKET=pmspp-archive
if [ "$(hostname)" != 'mail.prodata.nz' ] ; then
    STORAGE_BUCKET=rsta-portal-archive-test
else
    STORAGE_BUCKET=rsta-portal-archive
fi
export STORAGE_BUCKET
STORAGE_DIR=$HOME/prod/private-media/

[ ! -f docker-compose.yml ] && cd $HOME
sudo find ./archive -mtime +1 -exec rm -f {} \;
# Vacuum DBs once a week
[ $(date +%u) = '7' ] && psql -U postgres -c "VACUUM FULL ANALYZE;"
psql -U postgres -c "SELECT pg_backup_start('$TS_LABEL', false);"
sudo bash -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
# sudo -u postgres XZ_OPT="-9 --memory=135000000" tar -C "$DATA_DIR" -cJf ./backup/${TS_LABEL}_DB.tar.xz ./
sudo -u postgres tar -C "$DATA_DIR" -cJf ./backup/${TS_LABEL}_DB.tar.xz ./
psql -U postgres -c "SELECT pg_backup_stop();"
# [ $(date +%d) != '01' ] && NEWER="-N $(date +%Y-%m-01)"
# if [ "$(hostname)" != 'mail.prodata.nz' ] ; then
#     XZ_OPT="-9 --memory=135000000" tar -C ./prod/private-media/ --exclude ./PDF --exclude ./pdf --exclude ./converted $NEWER -cJf ./backup/${TS_LABEL}_MEDIA.tar.xz ./
# fi
# find -type f -mtime -2 | grep -Ev './converted|./PDF' | s3cmd --skip-existing --continue-put --files-from=-  sync . s3://rsta-portal-archive
# sudo -u chmod g+w ./backup/$TS_LABEL.tar.xz
sudo mv ./backup/${TS_LABEL}_*.tar.xz ./archive/ && sudo find ./archive -mtime +0 -exec rm -f {} \;

# SEE: https://www.vultr.com/docs/how-to-use-s3cmd-with-vultr-object-storage
if which s3cmd && [ -f $HOME/.s3cfg ] ; then
    s3cmd put ./archive/${TS_LABEL}_DB.tar.xz s3://$BUCKET/$(date +%y%m)/DB/${TS_LABEL}_DB.tar.xz
    # s3cmd put ./archive/${TS_LABEL}_MEDIA.tar.xz s3://$BUCKET/$(date +%y%m)/MEDIA/${TS_LABEL}_MEDIA.tar.xz
    if compgen -G "./archive/*.sql.xz" &>/dev/null ; then
        cd ./archive/
        # tar -cf ${TS_LABEL}_DUMPS.tar ./*.sql.xz
        s3cmd put "./$(ls -1rt | tail -n 1)" s3://$BUCKET/$(date +%y%m)/DUMPS/${TS_LABEL}_DUMPS.sql.xz
        find ./ -mtime +1 -name \*.sql.xz -exec rm -f {} \;
    fi
    (
        cd "${STORAGE_DIR}"
        find -type f -mmin -2160 | grep -Ev './converted|./PDF|./HASHES' | s3cmd -H --no-check-md5 --no-delete-removed --skip-existing --continue-put --files-from=- sync . s3://${STORAGE_BUCKET}
        # Delete +800 days of unmodified files making sure they are synced beforehand
        find \( -path ./converted -prune -o -path ./PDF -prune -o -path ./HASHES -prune \) -o -type f -mtime +800 -exec sh -c 's3cmd info -q "s3://rsta-portal-archive/${0#./}" 2>/dev/null' {} \; -print | xargs rm -f
    )
fi
