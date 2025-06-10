# MAILTO=
# SHELL=/bin/bash
TS_LABEL=$(date +%FT%s)
PATH=/bin:/usr/bin:/usr/local/sbin:/usr/sbin:/sbin:/opt/aws/bin:$HOME/.local/bin:$HOME/bin:$PATH:/usr/local/bin
DATA_DIR="$(psql  -U postgres postgres -0 -z -q  -t  -c 'show data_directory;'|tr -d ' ')"

[ ! -f docker-compose.yml ] && cd $HOME
sudo find ./archive -mtime +1 -exec rm -f {} \;
psql -U postgres -c "VACUUM FULL ANALYZE;"
psql -U postgres -c "SELECT pg_backup_start('$TS_LABEL', false);"
sudo bash -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
sudo -u postgres XZ_OPT="-9 --memory=135000000" tar -C "$DATA_DIR" -cJf ./backup/${TS_LABEL}_DB.tar.xz ./
psql -U postgres -c "SELECT pg_backup_stop();"
[ $(date +%d) != '01' ] && NEWER="-N $(date +%Y-%m-01)"
if [ "$(hostname)" != 'mail.prodata.nz' ] ; then
    XZ_OPT="-9 --memory=135000000" tar -C ./prod/private-media/ --exclude ./converted $NEWER -cJf ./backup/${TS_LABEL}_MEDIA.tar.xz ./
fi
# sudo -u chmod g+w ./backup/$TS_LABEL.tar.xz 
sudo mv ./backup/${TS_LABEL}_*.tar.xz ./archive/ && sudo find ./archive -mtime +0 -exec rm -f {} \;

# SEE: https://www.vultr.com/docs/how-to-use-s3cmd-with-vultr-object-storage
if which s3cmd && [ -f $HOME/.s3cfg ] ; then
    s3cmd put ./archive/${TS_LABEL}_DB.tar.xz s3://pmspp-archive/${TS_LABEL}_DB.tar.xz
    s3cmd put ./archive/${TS_LABEL}_MEDIA.tar.xz s3://pmspp-archive/${TS_LABEL}_MEDIA.tar.xz
    if compgen -G "./archive/*.sql.xz" &>/dev/null ; then
        cd ./archive/
        tar -cf ${TS_LABEL}_DUMPS.tar ./*.sql.xz
        find ./ -mtime +1 -name \*.sql.xz -exec rm -f {} \;
        s3cmd put ./${TS_LABEL}_DUMPS.tar s3://pmspp-archive/${TS_LABEL}_DUMPS.tar
    fi
fi
