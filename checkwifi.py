import os, sys, logging, argparse, ConfigParser
import time, datetime, pytz, dateutil.parser
import urllib2
from Adafruit_IO import Client as AIOClient

#
# this program is run by crontab every hour or so
# 0 * * * * python ~/prog.py >> ~/prog.log 2>&1 &
# it checks
# 1) if the internet is connected, if NOT we reboot
# 2) if last data update to Adafruit is too old, we reboot.
#    we read the local iot.ini file to get the AdafruitIO
#	 user name, sensor, feed and key information
# There are lots of cmd line overrides, running this with no
# args will be live
# log files in same directory as this script, with ".log"
#
# 20210222: better checker

defaults = {
	'inifile' : '/home/pi/src/iot.ini',	# inifile to get Adafruit keys
	'sensor'  : 'sensor-0',	# name of sensor ini section
	'feed'    : 'feed_t',	# name of feed ini section
	'stale'   : 3600,	# reboot if last update older than this (secs)
	'wait'    : 90,	# secs to wait after reboot before we start checking
}

# what drives all the decisions, filled in parse_arg, parse_inifile
config = None

########################################################################

def init_logging():
	'''Initalize the logger module

	The log files will be in the same directory as
	the python program, but extension is .log  
	'''
	logfile = os.path.abspath(sys.argv[0])[:-3] + ".log"
	logging.basicConfig(
		level=logging.DEBUG
		,format = '%(asctime)s [%(funcName)s][%(levelname)s] %(message)s'
		,datefmt = '%Y-%m-%d %H:%M:%S'
		,filename = logfile
		,filemode = "a")
#		,filename = logfile + "." + time.strftime("%Y%m%d_%H%M")

	# attach console stream (or is this stderr?)
	formatter = logging.Formatter( '%(asctime)s %(message)s', datefmt='%H:%M:%S')
	console   = logging.StreamHandler(sys.stdout)
	console.setLevel(logging.INFO)
	console.setFormatter(formatter)
	logging.getLogger(name=None).addHandler(console)
	logging.info("-"*30)

########################################################################

def	internet_connected():
	'''True if connected to the internet'''
	if config.nointernet:
		logging.info('internet NOT connected test')
		return False

	try:
		urllib2.urlopen('https://www.google.com',timeout=10)
		if config.verbose:
			logging.info('internet connected')
		return True
	except urllib2.URLError as e:
		logging.info(e)
		return False

########################################################################

def	uptime():
	'''Seconds since boot'''
	with open('/proc/uptime') as f:
		return int(float(f.readline().split()[0]))

########################################################################

def	parse_args():
	'''Parse cmdl line arguements

	Use the argparse module

	returns: 
		arg_parse Namespace structure
	'''
	global config
	parser = argparse.ArgumentParser()
	parser.add_argument('-v', '--verbose', action='store_true', 
		help='print out lots of values')
	parser.add_argument('-nr', '--noreboot', action='store_true', 
		help='do not reboot')
	parser.add_argument('-ni', '--nointernet', action='store_true', 
		help='force no internet test')
	parser.add_argument('-f', '--inifile', default=defaults['inifile'], 
	    help='inifile to use to get the AdafruitIO user and key')
	parser.add_argument('-s', '--stale', default=defaults['stale'],
		help='seconds with no updates before we reboot', type=int)
	parser.add_argument('-w', '--wait', default=defaults['wait'],
		help='seconds  towait after we reboot', type=int)
	parser.add_argument('-u', '--user',    
		help='adafruit user (read in from inifile)')
	parser.add_argument('-k', '--key',     
		help='adafruit key (read in from inifile)')
	parser.add_argument('-d', '--feed',    
		help='adafruit feed (read in from inifile)')
	config = parser.parse_args()
	if config.verbose:
		logging.info( 'finished parse_agrs' )

########################################################################

def	parse_inifile():
	'''Parse the supplied default of cmdline supplied  inifile

	args: 
		config: arg_parse Namespace structure
	returns: 
		arg_parse Namespace structure
	raises:
		Exception is the inifile is not found
	'''
	global config
	if not os.path.isfile(config.inifile) :
		raise Exception('Error: ini flle {} does not exist'.format(config.inifile))
	cp = ConfigParser.ConfigParser()
	cp.read(config.inifile)
	d = dict()
	d.update(dict(cp.items('adafruit-io')))
	d.update(dict(cp.items(defaults['sensor'])))
	config.feed = d[defaults['feed']]
	config.user = d['username']
	config.key  = d['key']
	if config.verbose:
		logging.info( 'finished parse_inifile' )
		logging.info( 'defaults={}'.format(defaults))
		logging.info( 'config={}'.format(config))
	
########################################################################

def	elapsed_seconds(timestr):
	'''Elapsed time (secs) from arg string

	Computes the elapsed seconds from now to the input string

	args:
		timestr: required (str)  fmt=YYYY-MM-DDTHH:MM:SSZ 
	returns:
		int seconds fomr timestr to now
	'''
	time = dateutil.parser.parse(timestr)
	now  = datetime.datetime.now(pytz.utc)
	return int((now-time).total_seconds())

########################################################################

def	reboot():
	'''Reboot the computer'''
	if config.noreboot:
		logging.info('Not rebooting, just print wall message')
		os.system('sudo shutdown -k') 
	else:
		logging.info('Rebooting: 60 seconds to cancel (sudo shutdown -c)')
		os.system('sudo shutdown -r 1') # 1 minute
			
########################################################################

def	wait_after_reboot():
	'''Wait a decent interval after a reboot'''
	seconds = uptime()
	logging.info( '{} seconds since last reboot'.format(seconds))
	if seconds < config.wait:	# seconds
		delay = max(10, config.wait - seconds)
		logging.info('sleeping for {} secs'.format(delay))
		time.sleep(delay)
		
########################################################################

def	get_seconds_ago_last_update():
	'''Seconds ago last update occured'''
	aio  = AIOClient(config.user, config.key)
	data = aio.receive(config.feed)
	if config.verbose:
		logging.info(data)
	return elapsed_seconds(data.created_at)

########################################################################

def	last_update_too_old():
	'''True if last Adafruit update too old'''
	seconds = get_seconds_ago_last_update()
	logging.info( 
		'{} seconds since last measurement, reboot if > {}'.format(
		seconds, config.stale))
	if seconds > config.stale: 
		return True
	return False

########################################################################

def	main():
	init_logging()
	parse_args()
	parse_inifile()

	# wait a decent interval after reboot to check
	wait_after_reboot()

	if internet_connected():
		if last_update_too_old():
			reboot()
	else:
		reboot()

########################################################################

if __name__ == '__main__':
	# don't ctach anything, this way we get a stack trace
	main()
