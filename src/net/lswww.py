#!/usr/bin/env python
# -*- coding: utf-8 -*-
# lswww v2.3.1 - A web spider library
# Copyright (C) 2006 Nicolas Surribas
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import sys
import re
import socket
import getopt
import os
import HTMLParser
import jsoncookie
import urlparse
import HTTP
import urllib

from distutils.sysconfig import get_python_lib
BASE_DIR = None
if '' in sys.path:
  sys.path.remove('')
for python_dir in sys.path:
  if os.path.isdir(os.path.join(python_dir, "wapiti")):
    BASE_DIR = os.path.join(python_dir, "wapiti")
    break
if not BASE_DIR:
  for lib_dir in [get_python_lib(prefix="/usr/local"), get_python_lib()]:
    if os.path.isdir(os.path.join(lib_dir, "wapiti")):
      BASE_DIR = os.path.join(lib_dir, "wapiti")
      sys.path.append(BASE_DIR)
      break
if not BASE_DIR:
  sys.path.append("")
  if "__file__" in dir():
    BASE_DIR = os.path.normpath(os.path.join(os.path.abspath(__file__), '..'))
  else:
    BASE_DIR = os.getcwd()

import requests
from htmlentitydefs import name2codepoint as n2cp
from xml.dom import minidom
from crawlerpersister import CrawlerPersister
import BeautifulSoup

class lswww:
  """
	lswww explore a website and extract links and forms fields.

Usage: python lswww.py http://server.com/base/url/ [options]

Supported options are:
-s <url>
--start <url>
	To specify an url to start with

-x <url>
--exclude <url>
	To exclude an url from the scan (for example logout scripts)
	You can also use a wildcard (*)
	Exemple : -x "http://server/base/?page=*&module=test"
	or -x http://server/base/admin/* to exclude a directory

-p <url_proxy>
--proxy <url_proxy>
	To specify a proxy
	Exemple: -p http://proxy:port/

-c <cookie_file>
--cookie <cookie_file>
	To use a cookie

-a <login%password>
--auth <login%password>
	Set credentials for HTTP authentication
	Doesn't work with Python 2.4

-r <parameter_name>
--remove <parameter_name>
	Remove a parameter from URLs

-v <level>
--verbose <level>
	Set verbosity level
	0: only print results
	1: print a dot for each url found (default)
	2: print each url

-t <timeout>
--timeout <timeout>
	Set the timeout (in seconds)

-n <limit>
--nice <limit>
  Define a limit of urls to read with the same pattern
  Use this option to prevent endless loops
  Must be greater than 0

-i <file>
--continue <file>
	This parameter indicates Wapiti to continue with the scan from the specified
  file, this file should contain data from a previous scan.
	The file is optional, if it is not specified, Wapiti takes the default file
  from \"scans\" folder.

-h
--help
	To print this usage message
  """

  SCOPE_DOMAIN  = "domain"
  SCOPE_FOLDER  = "folder"
  SCOPE_PAGE    = "page"
  SCOPE_DEFAULT = "default"

  root = ""
  server = ""
  tobrowse = []
  browsed = []
  proxies = {}
  excluded = []
  forms = []
  uploads = []
  allowed = ['php', 'html', 'htm', 'xml', 'xhtml', 'xht', 'xhtm',
            'asp', 'aspx', 'php3', 'php4', 'php5', 'txt', 'shtm',
            'shtml', 'phtm', 'phtml', 'jhtml', 'pl', 'jsp', 'cfm', 'cfml']
  verbose = 0
  auth_basic = []
  bad_params = []
  timeout = 6.0
  h = None
  global_headers = {}
  cookiejar = None
  scope = None
  link_encoding = {}

  persister = None

  # 0 means no limits
  nice = 0

  def __init__(self, root, http_engine=None, crawlerFile=None):
    self.h = http_engine
    if root.startswith("-"):
      print _("First argument must be the root url !")
      sys.exit(0)
    if root.find("://") == -1:
      root = "http://" + root
    if(self.__checklink(root)):
      print _("Invalid protocol:"), root.split("://")[0]
      sys.exit(0)
    if root[-1] != "/" and (root.split("://")[1]).find("/") == -1:
      root += "/"

    server = (root.split("://")[1]).split("/")[0]
    self.root     = HTTP.HTTPResource(root)   # Initial URL
    self.server   = server # Domain
    self.scopeURL = root   # Scope of the analysis
    
    self.tobrowse.append(self.root)
    self.persister = CrawlerPersister()

  def setTimeOut(self, timeout=6.0):
    """Set the timeout in seconds to wait for a page"""
    self.timeout = timeout

  def setProxy(self, proxy=""):
    """Set proxy preferences"""
    url_parts = urlparse.urlparse(proxy)
    protocol = url_parts.scheme
    host = url_parts.netloc
    if protocol in ["http", "https"]:
      if host:
        self.proxies[protocol] = "%s://%s/" % (protocol, host)

  def setNice(self, nice=0):
    """Set the maximum of urls to visit with the same pattern"""
    self.nice = nice

  def setScope(self, scope):
    self.scope = scope
    if scope == self.SCOPE_FOLDER:
      self.scopeURL = "/".join(self.root.url.split("/")[:-1]) + "/"
    elif scope == self.SCOPE_DOMAIN:
      self.scopeURL = "http://" + self.server

  def addStartURL(self, url):
    if(self.__checklink(url)):
      print _("Invalid link argument") + ":", url
      sys.exit(0)
    if(self.__inzone(url) == 0):
      self.tobrowse.append(HTTP.HTTPResource(url))

  def addExcludedURL(self, url):
    """Add an url to the list of forbidden urls"""
    self.excluded.append(url)

  def setCookieFile(self, cookie):
    """Set the file to read the cookie from"""
    if os.path.isfile(cookie):
      jc = jsoncookie.jsoncookie()
      jc.open(cookie)
      self.cookiejar = jc.cookiejar(self.server)
      jc.close()

  def setAuthCredentials(self, auth_basic):
    self.auth_basic = auth_basic

  def addBadParam(self, bad_param):
    self.bad_params.append(bad_param)

  def browse(self, web_resource):
    """Extract urls from a webpage and add them to the list of urls to browse if they aren't in the exclusion list"""
    url = web_resource.url

    # We don't need destination anchors
    current = url.split("#")[0]
    # Url without query string
    current = current.split("?")[0]
    # Get the dirname of the file
    currentdir = "/".join(current.split("/")[:-1]) + "/"

    # Timeout must not be too long to block big documents (for exemple a download script)
    # and not too short to give good results
    socket.setdefaulttimeout(self.timeout)

    headers = {}
    headers["user-agent"] = 'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)'
    try:
      if isinstance(web_resource, HTTP.HTTPResource):
        if web_resource.method == "POST":
          headers['content-type'] = 'application/x-www-form-urlencoded'
        resp = self.h.send(web_resource, headers=headers)
      else:
        print "non HTTPResource:", url
        sys.exit()
    except socket.timeout:
      self.excluded.append(url)
      return False
    except requests.exceptions.Timeout:
      self.excluded.append(url)
      return False
    except socket.error, msg:
      if msg.errno == 111:
        print _("Connection refused!")
      self.excluded.append(url)
      return False
    except Exception:
      self.excluded.append(url)
      return False

    info = resp.getHeaders()
    code = resp.getCode()
    info["status_code"] = code

    web_resource.setHeaders(info)

    if not url in self.link_encoding:
      self.link_encoding[url] = ""

    proto = url.split("://")[0]
    if proto == "http" or proto == "https":
      if not isinstance(proto, unicode): proto = unicode(proto)
      # Check the content-type first
      #if not info.has_key("content-type"):
        # Sometimes there's no content-type... so we rely on the document extension
      #  if (current.split(".")[-1] not in self.allowed) and current[-1] != "/":
      #    return info
      #elif info["content-type"].find("text") == -1:
      #  return info

    # No files more than 2MB
    if info.has_key("content-length"):
      if int(info["content-length"]) > 2097152:
        return False

    resp_encoding = resp.getEncoding()
    # Requests says it found an encoding... so the content must be some HTML
    if resp_encoding:
      # But Requests doesn't take a deep look at the webpage, so check it with BeautifulSoup
      page_encoding = BeautifulSoup.BeautifulSoup(resp.getRawPage()).originalEncoding
      if page_encoding and page_encoding.upper() != resp_encoding:
        # Mismatch ! Convert the response text to the encoding detected by BeautifulSoup
        resp.setEncoding(page_encoding)
      data = resp.getPage()
    else:
      # Can't find an encoding... beware of non-html content
      data = resp.getRawPage()

    # Manage redirections
    if info.has_key("location"):
      redir = self.correctlink(info["location"], current, currentdir, proto, None)
      if redir != None:
        if(self.__inzone(redir) == 0):
          self.link_encoding[redir] = self.link_encoding[url]
          redir = HTTP.HTTPResource(redir)
          # Is the document already visited of forbidden ?
          if (redir in self.browsed) or (redir in self.tobrowse) or \
              self.isExcluded(redir):
            pass
          else:
            # No -> Will browse it soon
            self.tobrowse.append(redir)

    htmlSource = data
    if page_encoding:
      bs = BeautifulSoup.BeautifulSoup(htmlSource)
      # Look for a base tag with an href attribute
      if bs.head:
        baseTags = bs.head.findAll("base")
        for base in baseTags:
          if base.has_key("href"):
            # Found a base url, now set it as the current url
            current = base["href"].split("#")[0]
            # We don't need destination anchors
            current = current.split("?")[0]
            # Get the dirname of the file
            currentdir = "/".join(current.split("/")[:-1]) + "/"
            break

    #if page_encoding != None:
    #  htmlSource = unicode(data, page_encoding, "ignore")
    #else:
    #  htmlSource = data

    p = linkParser(url)
    try:
      p.feed(htmlSource)
    except HTMLParser.HTMLParseError, err:
      htmlSource = BeautifulSoup.BeautifulSoup(htmlSource).prettify()
      if not isinstance(htmlSource, unicode) and page_encoding != None:
        htmlSource = unicode(htmlSource, page_encoding, "ignore")
      try:
        p.reset()
        p.feed(htmlSource)
      except HTMLParser.HTMLParseError, err:
        p = linkParser2(url, self.verbose)
        p.feed(htmlSource)

    # Sometimes the page is badcoded but the parser doesn't see the error
    # So if we got no links we can force a correction of the page
    if len(p.liens) == 0:
      if page_encoding != None:
        htmlSource = BeautifulSoup.BeautifulSoup(htmlSource).prettify(page_encoding)
      try:
        p.reset()
        p.feed(htmlSource)
      except HTMLParser.HTMLParseError, err:
        p = linkParser2(url, self.verbose)
        p.feed(htmlSource)

    for lien in p.uploads:
      self.uploads.append(self.correctlink(lien, current, currentdir, proto, page_encoding))
    for lien in p.liens:
      if lien != None and page_encoding != None and isinstance(lien, unicode):
        lien = lien.encode(page_encoding, "ignore")
      lien = self.correctlink(lien, current, currentdir, proto, page_encoding)
      if lien != None:
        if(self.__inzone(lien) == 0):
          # Is the document already visited of forbidden ?
          lien = HTTP.HTTPResource(lien, encoding=page_encoding)
          if (lien in self.browsed) or (lien in self.tobrowse) or self.isExcluded(lien):
            pass
          elif self.nice > 0:
            if self.__countMatches(lien.url) >= self.nice:
              # don't waste time next time we found it
              self.excluded.append(lien)
              return False
            else:
              self.tobrowse.append(lien)
          else:
            # No -> Will browse it soon
            self.tobrowse.append(lien)
          # Keep the encoding of the current webpage for the future requests to the link
          # so we can encode the query string parameters just as a browser would do.
          # Of course websites encoding may be broken :(
          self.link_encoding[lien] = page_encoding

    for form in p.forms:
      action = self.correctlink(form[0], current, currentdir, proto, page_encoding)
      if action == None:
        action = current

      # urlencode the POST parameters here
      params = form[1]
      for kv in params:
        if isinstance(kv[0], unicode):
          kv[0] = kv[0].encode(page_encoding, "ignore")
        if isinstance(kv[1], unicode):
          kv[1] = kv[1].encode(page_encoding, "ignore")

      form_rsrc = HTTP.HTTPResource(action, method = "POST", post_params = params, encoding = page_encoding, referer = url)
      if form_rsrc not in self.forms:
        self.forms.append(form_rsrc)
      if not (form_rsrc in self.browsed or form_rsrc in self.tobrowse):
        self.tobrowse.append(form_rsrc)
    # We automaticaly exclude 404 urls
    if code == "404":
      self.excluded.append(url)
      #return {} # exclude from scan but can be useful for some modules maybe

    return True


  def correctlink(self, lien, current_url, current_directory, protocol, encoding):
    """Transform relatives urls in absolutes ones"""

    if lien is None:
      return current_url

    # No leading or trailing whitespaces
    lien = lien.strip()
    
    if lien == "":
      return current_url

    if lien == "..":
      lien = "../"
    # bad protocols
    llien = lien.lower()
    if llien.find("telnet:", 0) == 0 or llien.find("ftp:", 0) == 0 or \
    llien.find("mailto:", 0) == 0 or llien.find("javascript:", 0) == 0 or \
    llien.find("news:", 0) == 0 or llien.find("file:", 0) == 0 or \
    llien.find("gopher:", 0) == 0 or llien.find("irc:", 0) == 0:
      return None
    # Good protocols or relatives links
    else:
      # full url, nothing to do :)
      if (lien.find("http://", 0) == 0) or (lien.find("https://", 0) == 0):
        pass
      else:
        # root-url related link
        if(lien[0] == '/'):
          lien = protocol + u"://" + self.server + lien
        else:
          # same page + query string
          if(lien[0] == '?'):
            lien = current_url + lien
          # current_url directory related link
          else:
            lien = current_directory + lien
      # No destination anchor
      if lien.find("#") != -1:
        lien = lien.split("#")[0]

      if "?" in lien:
        args = lien.split("?")[1]
        # if args is a unicode string, encode it according to the charset of the webpage (if known)
        if encoding and isinstance(args, unicode):
          args = args.encode(encoding, "ignore")
        if args.find("&") != -1 :
          args = args.split("&")
          args = [i for i in args if i != "" and i.find("=") >= 0]
          for i in self.bad_params:
            for j in args:
              if j.startswith(i + "="): args.remove(j)
          args = "&".join(args)

        lien = lien.split("?")[0]
        # First part of the url (path) must be encoded with UTF-8
        if isinstance(lien, unicode):
          lien = lien.encode("UTF-8", "ignore")
        lien = urllib.quote(lien, safe='/#%[]=:;$&()+,!?*')
        # a hack for auto-generated Apache directory index
        if args and not args in ["C=D;O=A", "C=D;O=D", "C=M;O=A", "C=M;O=D",
            "C=N;O=A", "C=N;O=D", "C=S;O=A", "C=S;O=D"]:
          lien = lien.split("?")[0] + "?" + args
      else:
        if isinstance(lien, unicode):
          lien = lien.encode("UTF-8", "ignore")
        lien = urllib.quote(lien, safe='/#%[]=:;$&()+,!?*')

      # Remove the trailing '?' if its presence doesn't make sense
      if lien[-1:] == "?":
        lien = lien[:-1]
      # remove useless slashes
      if lien.find("?") != -1:
        filename = lien.split("?")[0]
        filename = re.sub("([^:])//+", r"\1/", filename)
        if filename[-2:] == "/.":
          filename = filename[:-1]
        lien = filename + "?" + lien.split("?")[1]
      else:
        if lien[-2:] == "/.":
          lien = lien[:-1]
      # links going to a parrent directory (..)
      while re.search("/([~:!,;a-zA-Z0-9\.\-+_]+)/\.\./", lien) != None:
        lien = re.sub("/([~:!,;a-zA-Z0-9\.\-+_]+)/\.\./", "/", lien)
      lien = re.sub("/\./", "/", lien)
      # Everything is good here
      return lien

  def __checklink(self, url):
    """Verify the protocol"""
    if (url.find("http://", 0) == 0) or (url.find("https://", 0) == 0):
      return 0
    else:
      return 1

  def __inzone(self, url):
    """Make sure the url is under the root url"""
    if(url.find(self.scopeURL, 0) == 0):
      return 0
    else:
      return 1

  def isExcluded(self, http_resource):
    """Return True if the url is not allowed to be scan"""
    match = False
    for regexp in self.excluded:
      if self.__reWildcard(regexp, http_resource.url):
        match = True
    return match

  def __countMatches(self, url):
    """Return the number of known urls matching the pattern of the given url"""
    matches = 0
    if url.find("?") != -1:
      if url.find("=") != -1:
        i = 0
        for __ in xrange(0, url.count("=")):
          start = url.find("=", i)
          i = url.find("&", start)
          if i != -1:
            for u in self.browsed:
              if u.startswith(url[:start] + "=") and u.endswith(url[i:]):
                matches += 1
          else:
            for u in self.browsed:
              if u.startswith(url[:start] + "="):
                matches += 1
      else:#QUERY_STRING
        for a in [u for u in self.browsed if u.find("=") < 0]:
          if a.startswith(url.split("?")[0]):
            matches += 1
    return matches

  def __reWildcard(self, regexp, string):
    """Wildcard-based regular expression system"""
    regexp = re.sub("\*+", "*", regexp)
    match = True
    if regexp.count("*") == 0:
      if regexp == string:
        return True
      else:
        return False
    blocks = regexp.split("*")
    start = ""
    end = ""
    if not regexp.startswith("*"):
      start = blocks[0]
    if not regexp.endswith("*"):
      end = blocks[-1]
    if start != "":
      if string.startswith(start):
        blocks = blocks[1:]
      else:
        return False
    if end != "":
      if string.endswith(end):
        blocks = blocks[:-1]
      else:
        return False
    blocks = [block for block in blocks if block != ""]
    if blocks == []:
      return match
    for block in blocks:
      i = string.find(block)
      if i == -1: return False
      string = string[i + len(block):]
    return match

  def go(self, crawlerFile):
    # load of the crawler status if a file is passed to it.
    if crawlerFile != None:
      if self.persister.isDataForUrl(crawlerFile) == 1:
        self.persister.loadXML(crawlerFile)
        self.tobrowse = self.persister.getToBrose()
        # TODO: change xml file for browsed urls
        self.browsed  = self.persister.getBrowsed()
        self.forms    = self.persister.getForms()
        self.uploads  = self.persister.getUploads()
        print _("File") + " " + crawlerFile + " " + _("loaded, the scan continues") + ":"
        if self.verbose == 2:
          print " * " + _("URLs to browse")
          for x in self.tobrowse:
            print "    + " + x
          print " * " + _("URLs browsed")
          for x in self.browsed:
            print "    + " + x
      else:
        print _("File") + " " + crawlerFile + " " + _("not found, Wapiti will scan again the web site")

    # while url list isn't empty, continue browsing
    # if the user stop the scan with Ctrl+C, give him all found urls
    # and they are saved in an XML file
    try:
      while len(self.tobrowse) > 0:
        lien = self.tobrowse.pop(0)
        if (lien not in self.browsed and lien not in self.excluded):
          if self.browse(lien):
            if self.verbose == 1:
              sys.stderr.write('.')
            elif self.verbose == 2:
              print lien
            self.browsed.append(lien)

#            if not "link_encoding" in lien.headers:
#              if lien in self.link_encoding:
#                lien.headers["link_encoding"] = self.link_encoding[lien]
#            self.browsed[lien] = lien.headers

        if(self.scope == self.SCOPE_PAGE):
          self.tobrowse = []
      self.saveCrawlerData()
      print ""
      print " " + _("Notice") + " "
      print "========"
      print _("This scan has been saved in the file") + " " + self.persister.CRAWLER_DATA_DIR + '/' + self.server + ".xml"
      print _("You can use it to perform attacks without scanning again the web site with the \"-k\" parameter")
    except KeyboardInterrupt:
      self.saveCrawlerData()
      print ""
      print " " + _("Notice") + " "
      print "========"
      print _("Scan stopped, the data has been saved in the file") + " " + self.persister.CRAWLER_DATA_DIR + '/' + self.server + ".xml"
      print _("To continue this scan, you should launch Wapiti with the \"-i\" parameter")
      pass

  def verbosity(self, vb):
    """Set verbosity level"""
    self.verbose = vb

  def printLinks(self):
    """Print found URLs on standard output"""
    browsed.sort()
    sys.stderr.write("\n+ " + _("URLs") + ":\n")
    for lien in browsed:
      print lien

  def printForms(self):
    """Print found forms on standard output"""
    if self.forms != []:
      sys.stderr.write("\n+ "+_("Forms Info") + ":\n")
      for form in self.forms:
        print _("From") + ":", form[2]
        print _("To")   + ":", form[0]
        for k, v in form[1].items():
          print "\t" + k, ":", v
        print

  def printUploads(self):
    """Print urls accepting uploads"""
    if self.uploads != []:
      sys.stderr.write("\n+ " + _("Upload Scripts") + ":\n")
      for up in self.uploads:
        print up

  def exportXML(self, filename, encoding="UTF-8"):
    "Export the urls and the forms found in an XML file."
    xml = minidom.Document()
    items = xml.createElement("items")
    xml.appendChild(items)

    for lien in self.browsed:
      get = xml.createElement("get")
      get.setAttribute("url", lien.url)
      items.appendChild(get)

    for form in self.forms:
      post = xml.createElement("post")
      post.setAttribute("url", form[0])
      post.setAttribute("referer", form[2])

      for k, v in form[1].items():
        var = xml.createElement("var")
        var.setAttribute("name", k)
        var.setAttribute("value", v)
        post.appendChild(var)
      items.appendChild(post)

    for up in self.uploads:
      upl = xml.createElement("upload")
      upl.setAttribute("url", up)
      items.appendChild(upl)

    fd = open(filename,"w")
    xml.writexml(fd, "    ", "    ", "\n", encoding)
    fd.close()

  def getLinks(self):
    return self.browsed

  def getForms(self):
    return self.forms

  def getUploads(self):
    self.uploads.sort()
    return self.uploads

  def saveCrawlerData(self):
    self.persister.setRootURL(self.root);
    self.persister.setToBrose(self.tobrowse);
    self.persister.setBrowsed(self.browsed);
    self.persister.setForms  (self.forms);
    self.persister.setUploads(self.uploads);
    self.persister.saveXML(self.persister.CRAWLER_DATA_DIR + '/' + self.server + '.xml')

class linkParser(HTMLParser.HTMLParser):
  """Extract urls in 'a' href HTML tags"""
  def __init__(self, url = ""):
    HTMLParser.HTMLParser.__init__(self)
    self.liens = []
    self.forms = []
    self.form_values = []
    self.inform = 0
    self.inscript = 0
    self.current_form_url = url
    self.uploads = []
    self.current_form_method = "get"
    self.url = url

  def handle_starttag(self, tag, attrs):
    tmpdict = {}
    val = None
    for k, v in dict(attrs).items():
      tmpdict[k.lower()] = v
    if tag.lower() == 'a':
      if "href" in tmpdict:
        self.liens.append(tmpdict['href'])

    if tag.lower() == 'form':
      self.inform = 1
      self.form_values = []
      self.current_form_url = self.url
      if "action" in tmpdict:
        self.liens.append(tmpdict['action'])
        self.current_form_url = tmpdict['action']

      # Forms use GET method by default
      self.current_form_method = "get"
      if "method" in tmpdict:
        if tmpdict["method"].lower() == "post":
          self.current_form_method = "post"

    if tag.lower() == 'input':
      if self.inform == 1:
        if "type" not in tmpdict:
          tmpdict["type"] = "text"
        if "name" in tmpdict:
          if tmpdict['type'].lower() in ['text', 'password', 'radio',
              'checkbox', 'hidden', 'submit', 'search']:
          # use default value if present or set it to 'on'
            if "value" in tmpdict:
              if tmpdict["value"] != "":
                val = tmpdict["value"]
              else:
                val = u"on"
            else:
              val = u"on"
            self.form_values.append([tmpdict['name'], val])
          if tmpdict['type'].lower() == "file":
            self.uploads.append(self.current_form_url)

    if tag.lower() in ["textarea", "select"]:
      if self.inform == 1:
        if "name" in tmpdict:
          self.form_values.append([tmpdict['name'], u'on'])

    if tag.lower() in ["frame", "iframe"]:
      if "src" in tmpdict:
        self.liens.append(tmpdict['src'])

    if tag.lower() in ["img", "embed", "track", "source"]:
      if "src" in tmpdict:
        if "?" in tmpdict['src']:
          self.liens.append(tmpdict['src'])

    if tag.lower() == "script":
      self.inscript = 1
      if "src" in tmpdict:
        if "?" in tmpdict['src']:
          self.liens.append(tmpdict['src'])

  def handle_endtag(self, tag):
    if tag.lower() == 'form':
      self.inform = 0
      if self.current_form_method == "post":
        self.forms.append((self.current_form_url, self.form_values))
      else:
        l = ["=".join([k, v]) for k, v in self.form_values]
        l.sort()
        self.liens.append(self.current_form_url.split("?")[0] + "?" + "&".join(l))
    if tag.lower() == 'script':
      self.inscript = 0

  def handle_data(self, data):
    if self.inscript:
      candidates = re.findall(r'"([A-Za-z0-9_=#&%\.\+\?/-]*)"', data)
      candidates += re.findall(r"'([A-Za-z0-9_=#&%\.\+\?/-]*)'", data)
      for jstr in candidates:
        if '/' in jstr or '.' in jstr or '?' in jstr:
          self.liens.append(jstr)

class linkParser2:
  verbose = 0

  """Extract urls in 'a' href HTML tags"""
  def __init__(self, url="", verb=0):
    self.liens = []
    self.forms = []
    self.form_values = []
    self.inform = 0
    self.current_form_url = ""
    self.uploads = []
    self.current_form_method = "get"
    self.verbose = verb

  def __findTagAttributes(self, tag):
    attDouble = re.findall('<\w*[ ]| *(.*?)[ ]*=[ ]*"(.*?)"[ +|>]', tag)
    attSingle = re.findall('<\w*[ ]| *(.*?)[ ]*=[ ]*\'(.*?)\'[ +|>]', tag)
    attNone   = re.findall('<\w*[ ]| *(.*?)[ ]*=[ ]*["|\']?(.*?)["|\']?[ +|>]', tag)
    attNone.extend(attSingle)
    attNone.extend(attDouble)
    return attNone

  def feed(self, htmlSource):
    htmlSource = htmlSource.replace("\n", "")
    htmlSource = htmlSource.replace("\r", "")
    htmlSource = htmlSource.replace("\t", "")

    links = re.findall('<a.*?>', htmlSource)
    linkAttributes = []
    for link in links:
      linkAttributes.append(self.__findTagAttributes(link))

    #Finding all the forms: getting the text from "<form..." to "...</form>"
    #the array forms will contain all the forms of the page
    forms = re.findall('<form.*?>.*?</form>', htmlSource)
    formsAttributes = []
    for form in forms:
      formsAttributes.append(self.__findTagAttributes(form))

    #Processing the forms, obtaining the method and all the inputs
    #Also finding the method of the forms
    inputsInForms    = []
    textAreasInForms = []
    selectsInForms   = []
    for form in forms:
      inputsInForms   .append(re.findall('<input.*?>', form))
      textAreasInForms.append(re.findall('<textarea.*?>', form))
      selectsInForms  .append(re.findall('<select.*?>', form))

    #Extracting the attributes of the <input> tag as XML parser
    inputsAttributes = []
    for i in xrange(len(inputsInForms)):
      inputsAttributes.append([])
      for inputt in inputsInForms[i]:
        inputsAttributes[i].append(self.__findTagAttributes(inputt))

    selectsAttributes = []
    for i in xrange(len(selectsInForms)):
      selectsAttributes.append([])
      for select in selectsInForms[i]:
        selectsAttributes[i].append(self.__findTagAttributes(select))

    textAreasAttributes = []
    for i in xrange(len(textAreasInForms)):
      textAreasAttributes.append([])
      for textArea in textAreasInForms[i]:
        textAreasAttributes[i].append(self.__findTagAttributes(textArea))

    if(self.verbose == 3):
      print "\n\n" + _("Forms")
      print "====="
      for i in xrange(len(forms)):
        print _("Form") + " " + str(i)
        tmpdict = {}
        for k, v in dict(formsAttributes[i]).items():
          tmpdict[k.lower()] = v
        print " * " + _("Method") + ":  " + self.__decode_htmlentities(tmpdict['action'])
        print " * " + _("Intputs") + ": "
        for j in xrange(len(inputsInForms[i])):
          print "    + " + inputsInForms[i][j]
          for att in inputsAttributes[i][j]:
            print "       - " + str(att)
        print " * " + _("Selects") + ": "
        for j in xrange(len(selectsInForms[i])):
          print "    + " + selectsInForms[i][j]
          for att in selectsAttributes[i][j]:
            print "       - " + str(att)
        print " * " + _("TextAreas")+": "
        for j in xrange(len(textAreasInForms[i])):
          print "    + " + textAreasInForms[i][j]
          for att in textAreasAttributes[i][j]:
            print "       - " + str(att)
      print "\n"+_("URLS")
      print "===="

    for i in xrange(len(links)):
      tmpdict = {}
      for k, v in dict(linkAttributes[i]).items():
        tmpdict[k.lower()] = v
      if "href" in tmpdict:
        self.liens.append(self.__decode_htmlentities(tmpdict['href']))
        if(self.verbose == 3):
          print self.__decode_htmlentities(tmpdict['href'])

    for i in xrange(len(forms)):
      tmpdict = {}
      for k, v in dict(formsAttributes[i]).items():
        tmpdict[k.lower()] = v
      self.form_values = []
      if "action" in tmpdict:
        self.liens.append(self.__decode_htmlentities(tmpdict['action']))
        self.current_form_url = self.__decode_htmlentities(tmpdict['action'])

      # Forms use GET method by default
      self.current_form_method = "get"
      if "method" in tmpdict:
        if tmpdict["method"].lower() == "post":
          self.current_form_method = "post"

      for j in xrange(len(inputsAttributes[i])):
        tmpdict = {}
        for k, v in dict(inputsAttributes[i][j]).items():
          tmpdict[k.lower()] = v
          if "type" not in tmpdict:
            tmpdict["type"] = "text"
          if "name" in tmpdict:
            if tmpdict['type'].lower() in \
              ['text', 'password', 'radio', 'checkbox', 'hidden',
                  'submit', 'search']:
              # use default value if present or set it to 'on'
              if "value" in tmpdict:
                if tmpdict["value"] != "": val = tmpdict["value"]
                else: val = u"on"
              else: val = u"on"
              self.form_values.append([tmpdict['name'], val])
            if tmpdict['type'].lower() == "file":
              self.uploads.append(self.current_form_url)

      for j in xrange(len(textAreasAttributes[i])):
        tmpdict = {}
        for k, v in dict(textAreasAttributes[i][j]).items():
          tmpdict[k.lower()] = v
        if "name" in tmpdict:
          self.form_values.append([tmpdict['name'], u'on'])

      for j in xrange(len(selectsAttributes[i])):
        tmpdict = {}
        for k, v in dict(selectsAttributes[i][j]).items():
          tmpdict[k.lower()] = v
        if "name" in tmpdict:
          self.form_values.append([tmpdict['name'], u'on'])

      if self.current_form_method == "post":
        self.forms.append((self.current_form_url, self.form_values))
      else:
        l = ["=".join([k, v]) for k, v in self.form_values]
        l.sort()
        self.liens.append(self.current_form_url.split("?")[0] + "?" + "&".join(l))

  def __substitute_entity(self, match):
    ent = match.group(2)
    if match.group(1) == "#":
      return unichr(int(ent))
    else:
      cp = n2cp.get(ent)

      if cp:
        return unichr(cp)
      else:
        return match.group()

  def __decode_htmlentities(self, string):
    entity_re = re.compile("&(#?)(\d{1,5}|\w{1,8});")
    return entity_re.subn(self.__substitute_entity, string)[0]

  def reset(self):
    self.liens = []
    self.forms = []
    self.form_values = []
    self.inform = 0
    self.current_form_url = ""
    self.uploads = []
    self.current_form_method = "get"

if __name__ == "__main__":
  def _(text):
    return text
  try:
    auth = []
    xmloutput = ""
    crawlerFile = None

    if len(sys.argv)<2:
      print lswww.__doc__
      sys.exit(0)
    if '-h' in sys.argv or '--help' in sys.argv:
      print lswww.__doc__
      sys.exit(0)
    myls = lswww(sys.argv[1])
    myls.verbosity(1)
    try:
      opts, args = getopt.getopt(sys.argv[2:], "hp:s:x:c:a:r:v:t:n:e:ib:",
          ["help", "proxy=", "start=", "exclude=", "cookie=", "auth=",
           "remove=", "verbose=", "timeout=", "nice=", "export=", "continue",
           "scope="])
    except getopt.GetoptError, e:
      print e
      sys.exit(2)
    for o, a in opts:
      if o in ("-h", "--help"):
        print lswww.__doc__
        sys.exit(0)
      if o in ("-s", "--start"):
        if (a.find("http://", 0) == 0) or (a.find("https://", 0) == 0):
          myls.addStartURL(a)
      if o in ("-x", "--exclude"):
        if (a.find("http://", 0) == 0) or (a.find("https://", 0) == 0):
          myls.addExcludedURL(a)
      if o in ("-p", "--proxy"):
          myls.setProxy(a)
      if o in ("-c", "--cookie"):
        myls.setCookieFile(a)
      if o in ("-r", "--remove"):
        myls.addBadParam(a)
      if o in ("-a", "--auth"):
        if a.find("%") >= 0:
          auth = [a.split("%")[0], a.split("%")[1]]
          myls.setAuthCredentials(auth)
      if o in ("-v", "--verbose"):
        if str.isdigit(a):
          myls.verbosity(int(a))
      if o in ("-t", "--timeout"):
        if str.isdigit(a):
          myls.setTimeOut(int(a))
      if o in ("-n", "--nice"):
        if str.isdigit(a):
          myls.setNice(int(a))
      if o in ("-e", "--export"):
        xmloutput = a
      if o in ("-b", "--scope"):
        myls.setScope(a)
      if o in ("-i", "--continue"):
        crawlerPersister = CrawlerPersister()
        crawlerFile = crawlerPersister.CRAWLER_DATA_DIR + '/' + sys.argv[1].split("://")[1] + '.xml'
    try:
      opts, args = getopt.getopt(sys.argv[2:], "hp:s:x:c:a:r:v:t:n:e:i:b:",
          ["help", "proxy=", "start=", "exclude=", "cookie=", "auth=",
           "remove=", "verbose=", "timeout=", "nice=", "export=", "continue=",
           "scope="])
    except getopt.GetoptError, e:
      ""
    for o, a in opts:
      if o in ("-i", "--continue"):
        if a != '' and a[0] != '-':
          crawlerFile = a

    myls.go(crawlerFile)
    myls.printLinks()
    myls.printForms()
    myls.printUploads()
    if xmloutput != "":
      myls.exportXML(xmloutput)
  except SystemExit:
    pass
