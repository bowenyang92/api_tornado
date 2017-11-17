import tornado.ioloop
import tornado.web
import pymongo
from pymongo import MongoClient
import urllib
import tornado.escape
import bcrypt
import concurrent.futures
from tornado import gen
import uuid  
import my_auth
from my_auth import jwtauth
import os
import datetime
import json

from tornado.options import define, options

define("port", default=15010, help="run on the given port", type=int)
define("mongodb", default="184.105.242.130:19777", help="mongodb database ip and port")
define("debug", default=False, help="debug options, will print when option is on")

# A thread pool to be used for password hashing with bcrypt.  For none given in the () means the most resources
executor = concurrent.futures.ThreadPoolExecutor()

#debug flag
DEBUG = options.debug

__UPLOADS__ = "/root/workspace/webapp_tornado/static/"


class Application(tornado.web.Application):
  def __init__(self):
    handlers = [
      (r"/?", MainHandler),
      (r"/register", RegisterHandler),
      (r"/check", CheckTokenHandler),
      (r"/login", LoginHandler),
      (r"/logout", LogoutHandler),
      (r"/get_user", UserHandler),
      (r"/logout", LogoutHandler),
      (r"/upload", UploadHandler),
      (r"/user_contents", UserContentsHandler),
      (r"/delete", DeleteFileHandler),
      (r"/api/v1/read_db/?", DBHandler),
      (r"/api/v1/insert_db/[0-9][0-9][0-9][0-9]/?", DBHandler),
      (r"/static_content/(.*)", tornado.web.StaticFileHandler, {"path": "/root/workspace/webapp_tornado/static"}),
    ]

    settings = dict(
      cookie_secret="1b92da5e-ab07-43f6-b78e-804091eadc97",
    )

    tornado.web.Application.__init__(self, handlers, **settings)
    # or write as super(Application, self).__init__(handlers)
    user_db_username = urllib.quote_plus('user_admin')
    user_db_password = urllib.quote_plus('securitai_user135')
    self.user_db_client = MongoClient("mongodb://%s:%s@%s/user_db"%(user_db_username, user_db_password,options.mongodb),connect=False)
    self.user_db= self.user_db_client.user_db
    self.user_account=self.user_db.user_account
    self.user_contents=self.user_db.user_contents

class BaseHandler(tornado.web.RequestHandler):
  @property
  def user_account_db(self):
    return self.application.user_account
  @property
  def user_contents_db(self):
    return self.application.user_contents

  def get_current_user(self):
    return self.get_secure_cookie("user")

class UserHandler(BaseHandler):
  def get(self):
    if not self.current_user:
      self.write("please log in first")
    print "type is:"
    print type(self.current_user)
    print self.get_secure_cookie("user")
    print type(self.get_secure_cookie("user"))
    name = tornado.escape.xhtml_escape(self.current_user)
    self.write("Hello, "+ name)

class LogoutHandler(BaseHandler):
  def get(self):
    self.write("Clear Token")


@jwtauth
class CheckTokenHandler(BaseHandler):
  def get(self):
    token=self.request.headers.get('Authorization').split()[1]
    payload=my_auth.decode_auth_token(token)
    if not isinstance(payload, str):
      # not str, means decoded payload
      self.write("congrats, you have the correct token\n")
      self.write("user is: "+ payload['user_name'])
    else:
      # str, means exception warning
      self.write(payload)
  # def post(self):
  #   try:
  #     form_data = tornado.escape.json_decode(self.request.body)
  #   except:
  #     self.write("Invalid Form data format, only support JSON\n")
  #   token=form_data['token']
  #   decoded=my_auth.decode_auth_token(token)
  #   self.write(decoded)

    # self.redirect(self.get_argument("next", "/"))

class LoginHandler(BaseHandler):
  @gen.coroutine
  def post(self):
    ### Validate data format
    try:
      form_data = tornado.escape.json_decode(self.request.body)
    except:
      self.write("Invalid Form data format, only support JSON\n")

    ### Retrieve data from DB
    try:
      user_account_db_data=self.user_account_db.find_one({'user_name':form_data['user_name']});
      if(user_account_db_data==None):
        self.write("User name cannot be found")
        return
      user_input_pw=form_data["password"]
      user_db_pw=user_account_db_data['password']
    except:
      print "error in user account insert"
      self.write("Error in login to DB")
      return

    #since the salt is stored in the hashed password, so we hashpw it again using hashed pass
    hashed_password = yield executor.submit(
      bcrypt.hashpw, tornado.escape.utf8(user_input_pw),
      tornado.escape.utf8(user_db_pw))
    if hashed_password == user_db_pw:
      # password match
      response={}
      new_token=my_auth.encode_auth_token(form_data['user_name'])
      if isinstance(new_token, str):
        response['token']=new_token
        self.write(response)
      else:
        self.write("Internal Server Error")
    else:
      # password not match
      self.write("Password Incorrect")

class RegisterHandler(BaseHandler):
  @gen.coroutine
  def post(self):
    # if self.any_author_exists():
    #   raise tornado.web.HTTPError(400, "author already created")

    ### Validate data format
    try:
      form_data = tornado.escape.json_decode(self.request.body)
    except:
      self.write("Invalid Form data format, only support JSON\n")
      return
    ### Check user name dup
    user_account_db_data=self.user_account_db.find_one({'user_name':form_data['user_name']})
    if(not user_account_db_data==None):
      self.write("User name exists")
      return
    #create hashed password
    hashed_password = yield executor.submit(
      bcrypt.hashpw, tornado.escape.utf8(form_data["password"]),
      bcrypt.gensalt())

    #prepare form data to insert into db
    user_data_uuid=uuid.uuid4().hex
    form_data['face_doc_id']=form_data['user_name']+'-facelist-'+user_data_uuid
    form_data['user_FC_collection']=form_data['user_name']+'-FC-'+user_data_uuid
    form_data['password']=hashed_password
    if DEBUG:
      print "insert data"
      print form_data
    try:
      self.user_account_db.insert_one(form_data)
    except:
      print "error in user account insert"
      self.write("Error in register to DB")
      return

    #prepare three list db create
    new_face_list={
      "user_name"           : form_data['user_name'],
      "videos"              : [],
      "images"              : [],
      "white_list"          : [],
      "black_list"          : [],
      "unknown_list"        : [],
      "user_FC_collection"  : form_data['user_FC_collection']
    }
    try:
      self.user_contents_db.insert_one(new_face_list)
    except:
      print "error in user_to_face insert"
      self.write("Error in register to DB")
      return

    #prepare http api response
    response={}
    response['result']='register success'
    new_token=my_auth.encode_auth_token(form_data['user_name'])
    if isinstance(new_token, str):
      response['token']=new_token
      self.write(response)
    else:
      self.write("Internal Server Error")


class MainHandler(BaseHandler):
  def get(self):
    self.write("Hello, world")
  def post(self):
    # directly get all request body data as a dict
    data = tornado.escape.json_decode(self.request.body)
    # or can access a dict value by self.get_body_argument("message"), if the body has a key "message"
    print "received post data:"
    print data

class DBHandler(BaseHandler):
  def get(self):
    #RequestHandler.application is
    #The Application object serving this request
    try:
      all_user=self.user_account_db.find()
      self.write("Hello ,with mongo ,user data")
      for c in all_user:
        self.write("<br/>")
        self.write(c["user_name"])
        self.write(' at email: ' + c["email"])
    except:
      self.write("Error in getting from DB")

@jwtauth
class UploadHandler(BaseHandler):
  def post(self):
    user_name_dict=my_auth.extract_user(self.request)
    if isinstance(user_name_dict, str):
      self.finish(user_name_dict)
      return
    user_name=user_name_dict['user_name']
    try:
      fileinfo = self.request.files['file'][0]
      fname = fileinfo['filename']
      extn = os.path.splitext(fname)[1]
      file_type="images"
      if extn == '.jpg' or extn == '.png' :
        file_type="images"
      elif extn == '.mp4' or extn == '.avi' :
        file_type="videos"
      else:
        self.finish("file format not supported")
        return
      cname = str(uuid.uuid4()) + extn
      f_path=__UPLOADS__ + 'user_contents/'+user_name+'/'+file_type+'/'
      
      if not os.path.exists(f_path):
        os.makedirs(f_path)
      f_url=f_path+cname
      relative_path='user_contents/'+user_name+'/'+file_type+'/'+cname
      fh = open(f_url, 'w+')
      fh.write(fileinfo['body'])
      
      self.user_contents_db.update_one({"user_name":user_name},
        {"$push":
          {file_type:
            {"url":f_url, "datetime":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"tag":[] }
          }
        })
    except:
      self.finish('Internal upload DB error')
      return
    remote_url="http://50.227.54.146:15010/static_content/"+relative_path
    self.finish(cname + " is uploaded! Check url >> %s" %remote_url)


@jwtauth
class UserContentsHandler(BaseHandler):
  def get(self):
    user_name_dict=my_auth.extract_user(self.request)
    if isinstance(user_name_dict, str):
      self.finish(user_name_dict)
      return
    user_name=user_name_dict['user_name']
    print "current user:"
    print user_name
    try:
      user_res=self.user_contents_db.find_one({"user_name":user_name})
    except:
      self.finish('Access DB error')
      return
    del(user_res['_id'])
    self.finish(json.dumps(user_res))

@jwtauth
class DeleteFileHandler(BaseHandler):
  def post(self):
    user_name_dict=my_auth.extract_user(self.request)
    if isinstance(user_name_dict, str):
      self.finish(user_name_dict)
      return
    user_name=user_name_dict['user_name']
    print "current user:"
    print user_name

    ### Validate data format
    try:
      form_data = tornado.escape.json_decode(self.request.body)
    except:
      self.write("Invalid Form data format, only support JSON\n")
      return
    file_type=form_data["file_type"]
    file_url=form_data["file_url"]
    try:
      user_res=self.user_contents_db.update_one({"user_name":user_name},
        {"$pull":
          {file_type:
            {"url":file_url}
          }
        })
    except:
      self.finish('Access DB error')
      return
    os.remove(file_url)
    self.finish("delete success")

# def make_app():
#   return tornado.web.Application([
#     (r"/", MainHandler),
#   ])

def main():
  tornado.options.parse_command_line()
  app = Application()
  app.listen(options.port)
  server = tornado.httpserver.HTTPServer(app)
  # server.bind(options.port)
  # server.start(0)  # forks one process per cpu
  tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
  main()
    
