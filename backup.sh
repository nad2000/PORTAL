# MAILTO=
# SHELL=/bin/bash
TS_LABEL=$(date +%FT%s)
PATH=/bin:/usr/bin:/usr/local/sbin:/usr/sbin:/sbin:/opt/aws/bin:$HOME/.local/bin:$HOME/bin:$PATH:/usr/local/bin
DATA_DIR="$(psql  -U postgres postgres -0 -z -q  -t  -c 'show data_directory;'|tr -d ' ')"

[ ! -f docker-compose.yml ] && cd $HOME
psql -U postgres -c "VACUUM FULL ANALYZE;"
psql -U postgres -c "SELECT pg_start_backup('$TS_LABEL', false);"
sudo bash -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
sudo -u postgres XZ_OPT="-9 --memory=135000000" tar -C "$DATA_DIR" -cJf ./backup/${TS_LABEL}_DB.tar.xz ./
XZ_OPT="-9 --memory=135000000" tar -C ./prod/private-media/ -cJf ./backup/${TS_LABEL}_MEDIA.tar.xz ./
# sudo -u chmod g+w ./backup/$TS_LABEL.tar.xz 
mv ./backup/${TS_LABEL}_*.tar.xz ./archive/
psql -U postgres -c "SELECT pg_stop_backup();"
sudo find ./archive -mtime +2 -exec rm -f {} \;

# SEE: https://www.vultr.com/docs/how-to-use-s3cmd-with-vultr-object-storage
if which s3cmd && [ -f $HOME/.s3cfg ] ; then
    s3cmd put ./archive/${TS_LABEL}_DB.tar.xz s3://pmspp-archive/${TS_LABEL}_DB.tar.xz
    s3cmd put ./archive/${TS_LABEL}_MEDIA.tar.xz s3://pmspp-archive/${TS_LABEL}_MEDIA.tar.xz
fi
