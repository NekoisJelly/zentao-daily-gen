'''
@File: zentao-weekly-report.py
@Author: leon.li(l2m2lq@gmail.com)
@Date: 2019-01-16 13:34:14
'''

import argparse
import configparser
import os
import sys
import pymysql
import datetime
import itertools
import decimal
import smtplib
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email import encoders
import xlsxwriter

__version__ = '0.5'

class ZentaoWeeklyReport:
  """
  用于协助项目组进行工时统计
  1. 统计上周的工时情况
  2. 以Excel的方式邮件发送给具体人
  """

  def __init__(self, cfg_filename):
    conf = configparser.ConfigParser()
    conf.read(cfg_filename)
    self._zentao_url = conf.get('zentao', 'url')
    self._mysql_host = conf.get('zentao_db', 'host')
    self._mysql_port = int(conf.get('zentao_db', 'port'))
    self._mysql_user = conf.get('zentao_db', 'user')
    self._mysql_passwd = conf.get('zentao_db', 'password')
    self._weekly_report_users = ["'"+i+"'" for i in conf.get('weekly_report', 'users').split(',')]
    self._weekly_report_to_mails = [x.strip() for x in conf.get('weekly_report', 'to_mails').split(',') if x.strip() != '']
    self._weekly_report_cc_mails = []
    if conf.has_option('weekly_report', 'cc_mails'):
      self._weekly_report_cc_mails = [x.strip() for x in conf.get('weekly_report', 'cc_mails').split(',') if x.strip() != '']
    self._weekly_report_bcc_mails = []
    if conf.has_option('weekly_report', 'bcc_mails'):
      self._weekly_report_bcc_mails = [x.strip() for x in conf.get('weekly_report', 'bcc_mails').split(',') if x.strip() != '']
    self._mail_user = conf.get('core', 'mail_user')
    self._mail_host = conf.get('core', 'mail_host')
    self._mail_passwd = conf.get('core', 'mail_password')

  def _previous_week_range(self, date):
    """
    获取上周的起始日期和结束日期 
    """
    start_date = date + datetime.timedelta(-date.weekday(), weeks=-1)
    end_date = date + datetime.timedelta(-date.weekday() - 1)
    return start_date, end_date

  def _get_weekly_detail_data(self):
    sql = """
      SELECT A.task AS task_id, 
      C.name AS sprint_title, 
      D.name AS module_title, 
      B.name AS task_title, 
      B.story,
      B.finishedBy,
      B.closedBy,
      B.finishedDate,
      B.closedDate,
      B.estimate,
      A.consumed, B.left
      FROM (
        SELECT task, account, ROUND(SUM(consumed),1) AS consumed
        FROM zt_taskestimate
        WHERE date >= '{start_date}' AND date <= '{end_date}'
        AND account IN ({users}) 
        GROUP BY task, account 
      ) A
      LEFT JOIN zt_task B ON A.task = B.id
      LEFT JOIN zt_project C ON B.project = C.id
      LEFT JOIN zt_module D ON B.module = D.id
      WHERE B.status = 'closed' OR B.status = 'done'
      ORDER BY A.task ASC
      """
    start_date, end_date = self._previous_week_range(datetime.date.today())
    sql = sql.format(users=','.join(self._weekly_report_users), start_date=start_date, end_date=end_date)

    # Connect to the database
    print("Connect to the database...")
    conn = pymysql.connect(host=self._mysql_host,
                           port=self._mysql_port,
                           user=self._mysql_user,
                           password=self._mysql_passwd,
                           db='zentao',
                           cursorclass=pymysql.cursors.DictCursor) 
    try:   
      with conn.cursor() as cursor:
        cursor.execute(sql)
        rs = cursor.fetchall()
    finally:
      conn.close()
    return rs

  def _get_weekly_summary_data(self):
    sql = """
      SELECT
      B.finishedBy AS finished_guy,
      C.name AS sprint_title, 
      D.name AS module_title, 
      GROUP_CONCAT(DISTINCT B.closedBy SEPARATOR ',') AS closed_guy,
      SUM(A.consumed) AS consumed
      FROM (
        SELECT task, account, ROUND(SUM(consumed),1) AS consumed
        FROM zt_taskestimate
        WHERE date >= '{start_date}' AND date <= '{end_date}'
        AND account IN ({users})
        GROUP BY task, account
      ) A
      LEFT JOIN zt_task B ON A.task = B.id
      LEFT JOIN zt_project C ON B.project = C.id
      LEFT JOIN zt_module D ON B.module = D.id
      WHERE B.status = 'closed'
      GROUP BY finished_guy, sprint_title, module_title
    """
    start_date, end_date = self._previous_week_range(datetime.date.today())
    sql = sql.format(users=','.join(self._weekly_report_users), start_date=start_date, end_date=end_date)

    # Connect to the database
    print("Connect to the database...")
    conn = pymysql.connect(host=self._mysql_host,
                           port=self._mysql_port,
                           user=self._mysql_user,
                           password=self._mysql_passwd,
                           db='zentao',
                           cursorclass=pymysql.cursors.DictCursor) 
    try:   
      with conn.cursor() as cursor:
        cursor.execute(sql)
        rs = cursor.fetchall()
    finally:
      conn.close()
    return rs

  def gen_weekly_report(self):
    # 查询汇总数据
    summary_data = self._get_weekly_summary_data()
    # 查询明细数据
    detail_data = self._get_weekly_detail_data()

    # 写入Excel
    start_date, end_date = self._previous_week_range(datetime.date.today())
    xlsx_filename = 'Zentao Weekly Report ({s} ~ {e}).xlsx'.format(s=start_date, e=end_date)
    
    if os.path.exists(xlsx_filename):
      os.remove(xlsx_filename)
    
    workbook = xlsxwriter.Workbook(xlsx_filename)
    xlsx_title_format = workbook.add_format()
    xlsx_title_format.set_bold() 
    # 汇总数据页
    worksheet = workbook.add_worksheet('汇总数据')
    title = ['完成者', '所属迭代', '所属模块', '关闭人', '消耗工时']
    title_width = [10, 30, 30, 15, 10]
    for i in range(len(title)):
      worksheet.write(0, i, title[i], xlsx_title_format)
      worksheet.set_column(i, i, title_width[i])
    row = 1
    for i in summary_data:
      worksheet.write(row, 0, i['finished_guy'])
      worksheet.write(row, 1, i['sprint_title'])
      worksheet.write(row, 2, i['module_title'])
      worksheet.write(row, 3, i['closed_guy'])
      worksheet.write(row, 4, i['consumed'])
      row += 1

    # 明细数据页
    worksheet = workbook.add_worksheet('明细数据')
    title = ['任务ID', '所属迭代', '所属模块', '任务名称', '需求ID','完成人', '关闭人', 
      '完成时间', '关闭时间', '最初预计', '总消耗', '预计剩余']
    for i in range(len(title)):
      worksheet.write(0, i, title[i], xlsx_title_format)
    row = 1
    for i in detail_data:
      worksheet.write(row, 0, i['task_id'])
      worksheet.write(row, 1, i['sprint_title'])
      worksheet.write(row, 2, i['module_title'])
      worksheet.write(row, 3, i['task_title'])
      worksheet.write(row, 4, i['story'])
      worksheet.write(row, 5, i['finishedBy'])
      worksheet.write(row, 6, i['closedBy'])
      worksheet.write(row, 7, str(i['finishedDate']))
      worksheet.write(row, 8, str(i['closedDate']))
      worksheet.write(row, 9, i['estimate'])
      worksheet.write(row, 10, i['consumed'])
      worksheet.write(row, 11, i['left'])
      row += 1
    workbook.close()

    # 发送邮件
    subject = 'Zentao Weekly ({start_date}至{end_date})'.format(start_date=start_date, end_date=end_date)
    message = MIMEMultipart()
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = self._mail_user
    message['To'] = ','.join(self._weekly_report_to_mails)
    if self._weekly_report_cc_mails:
      message['Cc'] = ','.join(self._weekly_report_cc_mails)
    if self._weekly_report_bcc_mails:
      message['Bcc'] = ','.join(self._weekly_report_bcc_mails)

    message.attach(MIMEText('这是自动生成的禅道数据邮件。'))
    part = MIMEBase('application', "octet-stream")
    part.set_payload(open(xlsx_filename, "rb").read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', "attachment; filename='{f}'".format(f=xlsx_filename))
    message.attach(part)
    try:
      smtp = smtplib.SMTP_SSL(self._mail_host)
      print("connect to SMTP server...")
      conn_code, conn_msg  = smtp.connect(self._mail_host, 465)
      if conn_code != 220:
        print("SMTP connect reply code: {code}, message: {msg}".format(code=conn_code, msg=conn_msg))
        return False
      print("login in SMTP server...")
      smtp.login(self._mail_user, self._mail_passwd)
      smtp.sendmail(
        self._mail_user, 
        self._weekly_report_to_mails + self._weekly_report_cc_mails + self._weekly_report_bcc_mails,
        message.as_string()
      )
      smtp.quit()
      return True
    except smtplib.SMTPException as e:
      print(e)
    except Exception as e:
      print("Unexpected error:", e)
    return False

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Zentao Dialy Generator')
  parser.add_argument('--version', '-v', action='version', version='%(prog)s ' + __version__)
  parser.add_argument('--config', '-c', type=str, required=False, help='config file', metavar='config.ini')
  args = vars(parser.parse_args())
  cfg_filename = args['config']
  if not cfg_filename:
    print('using config.ini in current directory.')
    cfg_filename = 'config.ini'
  if not os.path.isfile(cfg_filename):
    print('{cfg} not found'.format(cfg=cfg_filename))
    sys.exit(1)
  gen = ZentaoWeeklyReport(cfg_filename)
  if not gen.gen_weekly_report():
    print("generating daily failed.")
  else:
    print("generating daily done.")
