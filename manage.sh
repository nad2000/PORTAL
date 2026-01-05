#!/usr/bin/env bash
export ENV=${ENV:-local}
export DJANGO_DEBUG=False
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
if [ -z "$VIRTUAL_ENV" ] ; then
  { [ -f $HOME/venv313/bin/activate ] && source $HOME/venv313/bin/activate; } || \
  { [ -f $HOME/venv311/bin/activate ] && source $HOME/venv311/bin/activate; } || \
  { [ -f $PWD/venv/bin/activate ] && source $PWD/venv/bin/activate; }
fi
python $SCRIPT_DIR/manage.py "$@"
