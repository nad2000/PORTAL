#!/usr/bin/env bash

DBUSER=pmspp
if [ ! -S /run/postgresql/.s.PGSQL.5432 ] ; then
  export PGHOST=localhost
fi
export PGOPTIONS='--client-min-messages=warning'
export PGDATABASE="${2-pmspp}"
export SCHEMA="${1-stage}"
export PGUSER=$DBUSER
export APP=stage
export PROPOSAL_MASTER=fm.proposal_master
export ECHO=all

function has_table() {
  psql -XSn10ztq -c "SELECT 1 FROM \"${SCHEMA}\".\"$1\" LIMIT 0" >&/dev/null && echo "*** \"${SCHEMA}\".\"$1\""; return $?
}

function has_column() {
  psql -XSn10ztq -c "SELECT \"$2\" FROM \"${SCHEMA}\".\"$1\" LIMIT 0" >&/dev/null && echo "*** \"${SCHEMA}\".\"$1\".\"$2\""; return $?;
}

function fix_numbers() {
local table_name=$1
psql <<EOF
SET search_path TO stage,"\$user",public;
-- Fix ${table_name} numbers:
UPDATE "${table_name}" AS d
SET number=f.code||d.number
FROM "fund" AS f
WHERE d.fund_id=f.id AND d.number ~ '^-';
EOF
}

declare -A fund
fund["000"]="00:000"
fund["00024"]="00:000"
fund["00025"]="00:000"
fund["brp"]="BR:BRP"
fund["brp24"]="BR:BRP"
fund["brp25"]="BR:BRP"
fund["chn"]="CN:CHN"
fund["chn24"]="CN:CHN"
fund["chn25"]="CN:CHN"
fund["coe"]="CE:COE"
fund["coe24"]="CE:COE"
fund["coe25"]="CE:COE"
fund["cop"]="CP:COP"
fund["cop24"]="CP:COP"
fund["cop25"]="CP:COP"
fund["cor"]="CO:COR"
fund["cor24"]="CO:COR"
fund["cor25"]="CO:COR"
fund["cou"]="CU:COU"
fund["cou24"]="CU:COU"
fund["cou25"]="CU:COU"
fund["cow"]="CW:COW"
fund["cow24"]="CW:COW"
fund["cow25"]="CW:COW"
fund["csf"]="CS:CSF"
fund["csf24"]="CS:CSF"
fund["csf25"]="CS:CSF"
fund["cst"]="CT:CST"
fund["cst24"]="CT:CST"
fund["cst25"]="CT:CST"
fund["ddu"]="DU:DDU"
fund["ddu24"]="DU:DDU"
fund["ddu25"]="DU:DDU"
fund["dfg"]="GE:DFG"
fund["dfg24"]="GE:DFG"
fund["dfg25"]="GE:DFG"
fund["eap"]="EA:EAP"
fund["eap24"]="EA:EAP"
fund["eap25"]="EA:EAP"
fund["eco"]="EC:ECO"
fund["eco24"]="EC:ECO"
fund["eco25"]="EC:ECO"
fund["fm"]="MF:MFP"
fund["fm24"]="MF:MFP"
fund["fm25"]="MF:MFP"
fund["mfp"]="MF:MFP"
fund["mfp22"]="MF:MFP"
fund["mfp25"]="MF:MFP"
fund["frg"]="DE:FRG"
fund["frg24"]="DE:FRG"
fund["frg25"]="DE:FRG"
fund["fri"]="FR:FRI"
fund["fri24"]="FR:FRI"
fund["fri25"]="FR:FRI"
fund["hpe"]="HP:HPE"
fund["hpe24"]="HP:HPE"
fund["hpe25"]="HP:HPE"
fund["icf"]="IC:ICF"
fund["icf24"]="IC:ICF"
fund["icf25"]="IC:ICF"
fund["ie-contracts"]="CA:CSG"
fund["ie-contracts24"]="CA:CSG"
fund["ie-contracts25"]="CA:CSG"
fund["ilf"]="IL:ILF"
fund["ilf24"]="IL:ILF"
fund["ilf25"]="IL:ILF"
fund["imf"]="IM:IMF"
fund["imf24"]="IM:IMF"
fund["imf25"]="IM:IMF"
fund["irs"]="IR:IRS"
fund["irs24"]="IR:IRS"
fund["irs25"]="IR:IRS"
fund["ist"]="IS:IST"
fund["ist24"]="IS:IST"
fund["ist25"]="IS:IST"
fund["iun"]="UN:IUN"
fund["iun24"]="UN:IUN"
fund["iun25"]="UN:IUN"
fund["jcf"]="JC:JCF"
fund["jcf24"]="JC:JCF"
fund["jcf25"]="JC:JCF"
fund["jcf_proposalsonline25"]="JC:JCF"
fund["jgh"]="JG:JGH"
fund["jgh24"]="JG:JGH"
fund["jgh25"]="JG:JGH"
fund["jrp"]="JR:JRP"
fund["jrp24"]="JR:JRP"
fund["jrp25"]="JR:JRP"
fund["jsp"]="JP:JSP"
fund["jsp24"]="JP:JSP"
fund["jsp25"]="JP:JSP"
fund["jvh"]="JH:JVH"
fund["jvh24"]="JH:JVH"
fund["jvh25"]="JH:JVH"
fund["kor"]="KR:KOR"
fund["kor24"]="KR:KOR"
fund["kor25"]="KR:KOR"
fund["lea"]="LE:LEA"
fund["lea24"]="LE:LEA"
fund["lea25"]="LE:LEA"
fund["mdf"]="FW:FWL"
fund["mdf24"]="FW:FWL"
fund["mdf25"]="FW:FWL"
fund["mwf"]="WF:MWF"
fund["mwf24"]="WF:MWF"
fund["mwf25"]="WF:MWF"
fund["rdf"]="RD:RDF"
fund["rdf22"]="RD:RDF"
fund["rdf24"]="RD:RDF"
fund["rdf25"]="RD:RDF"
fund["rf"]="RF:RFT"
fund["rf23"]="RF:RFT"
fund["rf24"]="RF:RFT"
fund["rf25"]="RF:RFT"
fund["rft_online_proposals25"]="RF:RFT"
fund["ris"]="RI:RIS"
fund["ris24"]="RI:RIS"
fund["ris25"]="RI:RIS"
fund["sca"]="SC:SCA"
fund["sca24"]="SC:SCA"
fund["sca25"]="SC:SCA"
fund["see"]="SE:SEE"
fund["see24"]="SE:SEE"
fund["see25"]="SE:SEE"
fund["spn"]="ES:SPN"
fund["spn24"]="ES:SPN"
fund["spn25"]="ES:SPN"
fund["trv"]="TR:TRV"
fund["trv24"]="TR:TRV"
fund["trv25"]="TR:TRV"
fund["twn"]="TW:TWN"
fund["twn24"]="TW:TWN"
fund["twn25"]="TW:TWN"
IFS=':' read DEFAULT_FUND DEFAULT_FUND3 <<< "${fund["$SCHEMA"]}"
# DEFAULT_FUND="'${DEFAULT_FUND}'"
# DEFAULT_FUND3="'${DEFAULT_FUND3}'"

# case $SCHEMA in
#   'fm')
#     DEFAULT_FUND="'MF'"
#     ;;
#   'rdf')
#     DEFAULT_FUND="'RD'"
#     ;;
#   'rf')
#     DEFAULT_FUND="'RF'"
#     ;;
#   'mdf')
#     DEFAULT_FUND="'FW'"
#     ;;
#   'jcf')
#     DEFAULT_FUND="'JC'"
#     ;;
#   *)
#     DEFAULT_FUND=NULL
#     ;;
# esac
# export DEFAULT_FUND3=$(psql -0t -c "SELECT code3 FROM fund WHERE code=${DEFAULT_FUND} LIMIT 1")

# psql -XSn10ztq -c "ALTER ROLE rfda SET search_path='stage,\"$user\",public';"
# >&/dev/null && echo "*** \"${SCHEMA}\".\"$1\""; return $?
