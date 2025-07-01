:
export ENV=${ENV:-local}
export DJANGO_DEBUG=False
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source $HOME/venv311/bin/activate
python $SCRIPT_DIR/manage.py "$@"
