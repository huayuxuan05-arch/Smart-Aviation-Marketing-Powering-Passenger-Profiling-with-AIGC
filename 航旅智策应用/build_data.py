import sys
from data_layer import build
if __name__ == '__main__':
    build('--rebuild' in sys.argv)
