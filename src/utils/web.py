# -*- coding: utf-8 -*-
"""
    passport.utils.web
    ~~~~~~~~~~~~~~

    Common function for web.

    :copyright: (c) 2017 by staugur.
    :license: MIT, see LICENSE for more details.
"""

import json, requests
from .tool import logger, gen_fingerprint
from .jwt import JWTUtil, JWTException
from .aes_cbc import CBC
from urllib import urlencode
from functools import wraps
from flask import g, request, redirect, url_for, make_response
from werkzeug import url_decode

jwt = JWTUtil()
cbc = CBC()

def set_cookie(uid, seconds=7200):
    """设置cookie"""
    sessionId = jwt.createJWT(payload=dict(uid=uid), expiredSeconds=seconds)
    return cbc.encrypt(sessionId)

def verify_cookie(cookie):
    """验证cookie"""
    if cookie:
        try:
            sessionId = cbc.decrypt(cookie)
        except Exception,e:
            logger.debug(e)
        else:
            try:
                success = jwt.verifyJWT(sessionId)
            except JWTException,e:
                logger.debug(e)
            else:
                # 验证token无误即设置登录态，所以确保解密、验证两处key切不可丢失，否则随意伪造！
                return success
    return False

def analysis_cookie(cookie):
    """分析获取cookie中payload数据"""
    if cookie:
        try:
            sessionId = cbc.decrypt(cookie)
        except Exception,e:
            logger.debug(e)
        else:
            try:
                success = jwt.verifyJWT(sessionId)
            except JWTException,e:
                logger.debug(e)
            else:
                # 验证token无误即设置登录态，所以确保解密、验证两处key切不可丢失，否则随意伪造！
                return jwt.analysisJWT(sessionId)["payload"]
    return dict()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.signin:
            return redirect(url_for('signIn'))
        return f(*args, **kwargs)
    return decorated_function

def anonymous_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.signin:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def oauth2_name2type(name):
    """将第三方登录根据name转化为对应数字
    @param name str: OAuth name
    1手机号 2邮箱 3GitHub 4qq 5微信 6百度 7新浪微博 8Coding 9码云
    """
    BIND = dict(
            mobile = 1,
            email = 2,
            github = 3,
            qq = 4,
            wechat = 5,
            wexin = 5,
            baidu = 6,
            weibo = 7,
            sinaweibo = 7,
            coding = 8,
            gitee = 9
    )
    return BIND[name]

def oauth2_genderconverter(gender):
    """性别转换器"""
    if gender:
        if gender in (u"男", "男", "man", "m", 0, "0"):
            return 1
        elif gender in (u"女", "女", "woman", "f", "female", 1, "1"):
            return 0
    return 2

class OAuth2(object):
    """OAuth2.0 Client基类"""

    def __init__(self, name, client_id, client_secret, redirect_url, authorize_url, access_token_url, get_userinfo_url, get_openid_url=None, **kwargs):
        """
        必选参数：
            name: 开放平台标识
            client_id: 开放平台申请的应用id
            client_secret: 开放平台申请的应用密钥
            redirect_url: 开放平台申请的应用回掉地址
            authorize_url: 开放平台的授权地址
            access_token_url: 开放平台的access_token请求地址
            get_userinfo_url: 开放平台的用户信息请求地址
            get_openid_url: 开放平台的获取用户唯一标识请求地址，可选
        可选参数：
            scope: 申请权限，保持默认即可
            state: client端的状态值，可随机可校验，防CSRF攻击
            access_token_method: 开放平台的access_token请求方法，默认post，仅支持get、post
            get_userinfo_method: 开放平台的用户信息请求方法，默认get，仅支持get、post
            get_openid_method: 开放平台的获取用户唯一标识请求方法，默认get，仅支持get、post
            content_type: 保留
        """
        self._name = name
        self._consumer_key = client_id
        self._consumer_secret = client_secret
        self._redirect_url = redirect_url
        self._authorize_url = authorize_url
        self._access_token_url = access_token_url
        self._get_openid_url = get_openid_url
        self._get_userinfo_url = get_userinfo_url
        self._encoding = "utf-8"
        self._response_type = "code"
        self._scope = kwargs.get("scope", "")
        self._state = kwargs.get("state", gen_fingerprint(n=8))
        self._access_token_method = kwargs.get("access_token_method", "post").lower()
        self._get_openid_method = kwargs.get("get_openid_method", "get").lower()
        self._get_userinfo_method = kwargs.get("get_userinfo_method", "get").lower()
        self._content_type = kwargs.get("content_type", "application/json")
        self._requests = requests.Session()

    @property
    def requests(self):
        # 请求函数，同requests
        return self._requests

    def authorize(self, **params):
        '''登录的第一步：请求授权页面以获取`Authorization Code`
        :params: 其他请求参数
        '''
        _request_params = self._make_params(
            response_type=self._response_type,
            client_id = self._consumer_key,
            redirect_uri = self._redirect_url,
            state = self._state,
            scope = self._scope,
            **params
        )
        return redirect(self._authorize_url + "?" + _request_params)

    def authorized_response(self):
        '''登录第二步：授权回调，通过`Authorization Code`获取`Access Token`'''
        code = request.args.get("code")
        # state 可以先写入redis并设置过期，此处做验证，增强安全
        state = request.args.get("state")
        if code:
            _request_params = self._make_params(
                grant_type = "authorization_code",
                client_id = self._consumer_key,
                client_secret = self._consumer_secret,
                code = code,
                redirect_uri = self._redirect_url
            )
            url = self._access_token_url + "?" + _request_params
            resp = self.requests.get(url) if self._access_token_method == 'get' else self.requests.post(url)
            try:
                data = resp.json()
            except:
                data = resp.text
            # 包含access_token、expires_in、refresh_token等数据
            return data

    def get_openid(self, access_token, **params):
        '''登录第三步准备：根据access_token获取用户唯一标识id'''
        _request_params = self._make_params(
            access_token = access_token,
            **params
        )
        if not self._get_openid_url:
            return None
        url = self._get_openid_url + "?" + _request_params
        resp = self.requests.get(url) if self._get_openid_method == 'get' else self.requests.post(url)
        try:
            data = resp.json()
        except:
            data = resp.text
        return data

    def get_userinfo(self, access_token, **params):
        '''登录第三步：根据access_token获取用户信息(部分开放平台需要先获取openid、uid，可配置get_openid_url，先请求get_openid接口)'''
        _request_params = self._make_params(
            access_token = access_token,
            **params
        )
        url = self._get_userinfo_url + "?" + _request_params
        resp = self.requests.get(url) if self._get_userinfo_method == 'get' else self.requests.post(url)
        try:
            data = resp.json()
        except:
            data = resp.text
        return data

    def goto_signIn(self, uid):
        """OAuth转入登录流程，表示登录成功，需要设置cookie"""
        sessionId = set_cookie(uid=uid)
        response = make_response(redirect(url_for("index")))
        # 设置cookie根据浏览器周期过期，当无https时去除`secure=True`
        secure = False if request.url_root.split("://")[0] == "http" else True
        response.set_cookie(key="sessionId", value=sessionId, max_age=None, httponly=True, secure=secure)
        return response

    def goto_signUp(self, openid):
        """OAuth转入注册绑定流程"""
        return redirect(url_for("OAuthGuide", openid=openid))

    def _make_params(self, **kwargs):
        """传入编码成url参数"""
        return urlencode(kwargs)

    def url_code(self, content):
        '''
        parse string, such as access_token=E8BF2BCAF63B7CE749796519F5C5D5EB&expires_in=7776000&refresh_token=30AF0BD336324575029492BD2D1E134B.
        return data, such as {'access_token': 'E8BF2BCAF63B7CE749796519F5C5D5EB', 'expires_in': '7776000', 'refresh_token': '30AF0BD336324575029492BD2D1E134B'}
        '''
        return url_decode(content, charset=self._encoding).to_dict() if content else None

# 邮件模板：参数依次是邮箱账号、使用场景、验证码
email_tpl = u"""<!DOCTYPE html><html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><style>a{text-decoration: none}</style></head><body><table style="width:550px;"><tr><td style="padding-top:10px; padding-left:5px; padding-bottom:5px; border-bottom:1px solid #D9D9D9; font-size:16px; color:#999;">SaintIC Passport</td></tr><tr><td style="padding:20px 0px 20px 5px; font-size:14px; line-height:23px;">尊敬的<b>%s</b>，您正在申请<i>%s</i><br><br>申请场景的邮箱验证码是 <b style="color: red">%s</b><br><br>5分钟有效，请妥善保管验证码，不要泄露给他人。<br></td></tr><tr><td style="padding-top:5px; padding-left:5px; padding-bottom:10px; border-top:1px solid #D9D9D9; font-size:12px; color:#999;">此为系统邮件，请勿回复<br/>请保管好您的邮箱，避免账户被他人盗用<br/><br/>如有任何疑问，可查看网站帮助 <a target="_blank" href="https://passport.saintic.com">https://passport.saintic.com</a></td></tr></table></body></html>"""

def dfr(res, language="zh_CN"):
    """定义前端返回，将res中msg字段转换语言
    @param res dict: like {"msg": None, "success": False}, 英文格式
    @param language str: `zh_CN 简体中文`, `zh_HK 繁体中文`
    """
    # 翻译转换字典库
    trans = dict(
        zh_CN = {
            "Hello World": u"世界，你好",
            "Account already exists": u"账号已存在",
            "System is abnormal": u"系统异常，请稍后再试",
            "Registration success": u"注册成功",
            "Registration failed": u"注册失败",
            "Check failed": u"校验未通过",
            "Email already exists": u"邮箱已存在",
            "Invalid verification code": u"无效的验证码",
            "Invalid password: Inconsistent password or length failed twice": u"无效的密码：两次密码不一致或长度不合格",
            "Not support phone number registration": u"暂不支持手机号注册",
            "Invalid account": u"无效的账号",
            "Wrong password": u"密码错误",
            "Invalid account: does not exist or has been disabled": u"无效的账号：不存在或已禁用",
            "Invalid password: length unqualified": u"无效的密码：长度不合格",
            "Temporarily do not support phone number login": u"暂不支持手机号登录",
            "Have sent the verification code, please check the mailbox": u"已发送过验证码，请查收邮箱",
            "Sent verification code, valid for 300 seconds": u"已发送验证码，有效期300秒",
            "Mail delivery failed, please try again later": u"邮件发送失败，请稍后重试",
            "Third-party login binding failed": u"第三方登录绑定失败",
            "Has been bound to other accounts": u"已经绑定其他账号",
            "Operation failed, rolled back": u"操作失败，已回滚",
        },
        zh_HK = {
            "Hello World": u"世界，你好",
            "Account already exists": u"帳號已存在",
            "System is abnormal": u"系統异常",
            "Registration success": u"注册成功",
            "Registration failed": u"注册失敗",
            "Check failed": u"校驗未通過",
            "Email already exists": u"郵箱已存在",
            "Invalid verification code": u"無效的驗證碼",
            "Invalid password: Inconsistent password or length failed twice": u"無效的密碼：兩次密碼不一致或長度不合格",
            "Not support phone number registration": u"暫不支持手機號注册",
            "Invalid account": u"無效的帳號",
            "Wrong password": u"密碼錯誤",
            "Invalid account: does not exist or has been disabled": u"無效的帳號：不存在或已禁用",
            "Invalid password: length unqualified": u"無效的密碼：長度不合格",
            "Temporarily do not support phone number login": u"暫不支持手機號登入",
            "Have sent the verification code, please check the mailbox": u"已發送過驗證碼，請查收郵箱",
            "Sent verification code, valid for 300 seconds": u"已發送驗證碼，有效期300秒",
            "Mail delivery failed, please try again later": u"郵件發送失敗，請稍後重試",
            "Third-party login binding failed": u"第三方登錄綁定失敗",
            "Has been bound to other accounts": u"已經綁定其他賬號",
            "Operation failed, rolled back": u"操作失敗，已回滾",
        }
    )
    if isinstance(res, dict):
        if res.get("msg"):
            msg = res["msg"]
            try:
                new = trans[language][msg]
            except KeyError,e:
                logger.warn(e)
            else:
                res["msg"] = new
    return res