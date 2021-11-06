import os, sys, time, boto3
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException


# global variables
driver = None
chromeDriverPath = os.getcwd() + '/driver/chromedriver'
downloadPath = os.getcwd() + '/download'
userAgent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36'


def send_email(msg):
    import smtplib
    from email.mime.text import MIMEText

    identifier = sys.argv[1]
    password = sys.argv[2]
    emailAddress = '{}@naver.com'.format(identifier)
    
    server = smtplib.SMTP_SSL('smtp.naver.com', 465)
    server.login(emailAddress, password)
    
    email = MIMEText("PANIC: unexpected error at '{}'".format(msg))
    email['Subject'] = 'HYnoti'
    email['From'] = emailAddress
    email['To'] = emailAddress
    server.sendmail(emailAddress, emailAddress, email.as_string())
    server.quit()


def panic(func):
    global driver

    driver.quit()
    send_email(func)
    sys.exit(0)


def save_portal_notice(category, title, writer, date, content, files):
    from db import connect_db

    global driver

    client, collection = connect_db('portal')
    fileLinks = str()
    
    # for example, fileLinks = 'a.pdf|b.pdf|c.hwp' or ''
    for name in files:
        fileLinks += 'https://hynotifile.s3.ap-northeast-2.amazonaws.com/portal/{}/{}|'.format(title, name)
    fileLinks = fileLinks[:-1]
        
    # save a notice data to mongodb
    try:
        collection.insert_one({
            'category': category,
            'title': title,
            'writer': writer,
            'date': date,
            'content': str(content),
            'file': fileLinks
        })
    except DuplicateKeyError:
        # exception which is not an error
        print('the data has already been saved! stop crawling..')
        client.close()
        driver.quit()
        raise DuplicateKeyError('duplicate document')
    except:
        client.close()
        panic('save_portal_notice')

    client.close()


def upload_file(title, fileNum):
    import botocore
    global downloadPath, driver
    
    # notice has no attached files
    if fileNum == 0:
        return []
    
    fileNames = set()
    
    # check all files are downloaded to local
    while len(fileNames) != fileNum:
        for file in os.scandir(downloadPath):
            fileNames.add(file.name)
        time.sleep(1)

    # upload files to aws s3
    s3 = boto3.client('s3')
    for name in fileNames:
        filePath = '{}/{}'.format(downloadPath, name)
        bucket = 'hynotifile'
        objectName = 'portal/{}/{}'.format(title, name)
        
        try:
            s3.upload_file(filePath, bucket, objectName)
        except botocore.exceptions.ClientError:
            for file in os.scandir(downloadPath):
                os.remove(file.path)
            panic('upload_file(due to ClientError)')
        except:
            # before close program, remove files from local
            for file in os.scandir(downloadPath):
                os.remove(file.path)
            panic('upload_file')
    
    # remove files from local
    for file in os.scandir(downloadPath):
          os.remove(file.path)

    return [name for name in fileNames]
                
    
def get_notice_body(bsObj):
    global driver

    try:
        # all portal contents are within td html tag.
        content = bsObj.select_one('td#contents')
        files = bsObj.select('#detail > tbody > tr:last-child > td > div')
    except:
        panic('get_notice_body')

    # download all attached files by clicking them
    if files:
        for num, div in enumerate(files, 1):
            driver.find_element_by_xpath('//*[@id="detail"]/tbody/tr[6]/td/div[{}]/a'.format(num)).click()
            time.sleep(2)
    else:
        num = 0

    return content, num


def get_notice_header(bsObj):
    global driver

    try:
        category = bsObj.select_one('#gongjiNm').get_text()
        title = bsObj.select_one('td > #title').get_text()
        department = bsObj.select_one('td > #sosokNm').get_text()
        name = bsObj.select_one('td > #name').get_text()
        date = bsObj.select_one('#insertDate').get_text()
    except:
        panic('parse_notice_head')

    writer = department + ' / ' + name
    arr = date.strip().split('.')
    year = int(arr[0])
    month = int(arr[1])
    day = int(arr[2])
    print('[{}] {} {} {}'.format(category, title, writer, date))

    return category, title, writer, datetime(year, month, day)


def wait_until_notices_appear(second, element, location):
    global driver

    try:
        WebDriverWait(driver, second).until(EC.presence_of_element_located((element, location)))
    except TimeoutException:
        # if panic function is called, increase the seconds
        panic('wait_until_notices_appear')


def wait_until_files_loaded(second, element, location):
    global driver

    try:
        WebDriverWait(driver, second).until(EC.presence_of_element_located((element, location)))
    except TimeoutException:
        # some notices don't have files, which raises timeout exception.
        # but that is not abnormal situation. so just pass
        pass


def crawl():
    global driver
    pageLinks = ['//*[@id="pagingPanel"]/span[3]/span',
                 '//*[@id="pagingPanel"]/span[3]/a[1]',
                 '//*[@id="pagingPanel"]/span[2]/a[2]',
                 '//*[@id="pagingPanel"]/span[2]/a[3]',
                 '//*[@id="pagingPanel"]/span[2]/a[4]']  # up to 5 pages
    
    for pageNum, link in enumerate(pageLinks):
        # after the first page, click page number to move to that page.
        # and wait 5 seconds all notice lists to appear
        if pageNum > 0:
            driver.find_element_by_xpath(link).click()
            time.sleep(5)
            # NOTE: don't use wait_until_notices_appear(5, By.CSS_SELECTOR, '#mainGrid > tbody > tr:nth-child(10)')

        # get html code of current page to parse
        pageHTML = driver.page_source
        pageBsObj = BeautifulSoup(pageHTML, 'html.parser')

        # a notice header consists of category, title, writer, written date.
        # 10 headers exist per a page which points to each notice 
        headerBsObjs = pageBsObj.select('#mainGrid > tbody > tr')

        # repeate parsing for every notices in the page. 10 notices per a page
        for idx, headerBsObj in enumerate(headerBsObjs, 1):
            # parse notice header information
            category, title, writer, date = get_notice_header(headerBsObj)

            # and enter to the notice by clicking notice header and wait until all contents appear.
            # NOTE: when notice contents(e.g., text, image, files,,) are loaded, files are loaded at the end 
            driver.find_element_by_xpath('//*[@id="mainGrid"]/tbody/tr[{}]'.format(idx)).click()
            wait_until_files_loaded(5, By.CSS_SELECTOR, '#detail > tbody > tr:last-child > td > div')

            # get html code of current notice to parse
            noticeHTML = driver.page_source
            noticeBsObj = BeautifulSoup(noticeHTML, 'html.parser')

            # parse notice content and file
            content, fileNum = get_notice_body(noticeBsObj)
            # save files to aws s3 
            fileNames = upload_file(title, fileNum)
            # save notice information including file links to db
            save_portal_notice(category, title, writer, date, content, fileNames)

            # return to the page
            driver.find_element_by_xpath('//*[@id="btn_list"]').click()
            wait_until_notices_appear(5, By.CSS_SELECTOR, '#mainGrid > tbody > tr:nth-child(10)')
            
    # terminate chrome driver
    driver.quit()
        

# TODO
def handle_password_change_recommendation_page():
    pass


def submit_selfcheck():
    for num in range(37, 43):
        driver.find_element_by_xpath('//*[@id="c{}_b"]'.format(num)).click()
    driver.find_element_by_xpath('//*[@id="btn_confirm"]').click()
    
    
def handle_alert():
    try:
        WebDriverWait(driver, 5).until(EC.alert_is_present())
    except TimeoutException:
        pass
    else:
        driver.switch_to.alert.dismiss()
        
    
def handle_covid19_selfcheck():
    global driver

    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '#mainForm > div.title.mb-10 > span')))
    except TimeoutException:
        pass
    except UnexpectedAlertPresentException:
        handle_alert()
    except:
        panic('handle_covid19_selfcheck')
    else:
        submit_selfcheck()
        handle_alert()

        
def login():
    global driver

    # change language to korean
    driver.find_element_by_xpath('//*[@id="footer"]/div/ul/li[3]/ul/li[1]/a').click()
    time.sleep(2)

    # when in course registration period, course registration popup appears again
    # after changing language option
    handle_course_registration_popup()
    
    # input id and password and click login button
    identifier = sys.argv[1]
    password = sys.argv[2]
    driver.find_element_by_name('userId').send_keys(identifier)
    driver.find_element_by_name('password').send_keys(password)
    driver.find_element_by_xpath('//*[@id="hyinContents"]/div[1]/form/div/fieldset/p[3]/a').click()
        
        
def handle_course_registration_popup():
    global driver

    try:
        popup = driver.find_element_by_id('pop_po_sugang')
    except:
        panic('handle_course_registration_popup')
    else:
        style = popup.get_attribute('style')
        # pop up is visible
        if 'none' not in style:
            driver.find_element_by_xpath('//*[@id="pop_po_sugang"]/table/tbody/tr[1]/td/table/tbody/tr[1]/td[2]').click()

            
def handle_covid19_page():
    global driver

    try:
        button = driver.find_element_by_xpath('/html/body/div[1]/p')
    except:
        panic('handle_covid19_page')
    else:
        button.click()        
    
    
def enter_portal_notice():
    global driver

    driver.get('https://portal.hanyang.ac.kr/sso/lgin.do')
    
    handle_covid19_page()
    handle_course_registration_popup() # only for course registration period
    login()
    handle_covid19_selfcheck()
    # TODO: handle_password_change_recommendation_page()

    portalNoticeUrl = 'https://portal.hanyang.ac.kr/port.do'\
        '#!UDMwODIwMCRAXiRAXmNvbW0vZ2pzaCRAXk0wMDYyNjMkQF7qs7Xsp4Ds'\
        'gqztla0kQF5NMDAzNzgxJEBeMGJlMjk1OTM2MjY0MjlkZmMzZjFiNjE4MDQ'\
        '1YmM4MTcyYjg2ODMyZGYwZDMzM2JjMGY1ZGI0NzE5OWI5MDI4YQ=='
    # after passing all steps, access to portal notice
    driver.get(portalNoticeUrl)
    # wait the first page notices to be fully loaded
    wait_until_notices_appear(5, By.CSS_SELECTOR, '#mainGrid > tbody > tr:nth-child(10)')
    
    
def set_chromedriver():
    global driver, downloadPath, userAgent, chromeDriverPath
    
    options = webdriver.ChromeOptions()
    options.add_experimental_option('prefs', {'download.default_directory': downloadPath})
    options.add_argument('user-agent={}'.format(userAgent))
    options.add_argument('window-size=1920x1080')
    options.add_argument('start-maximized')
    options.add_argument('headless')
    # options.add_argument('no-sandbox')
    # options.add_argument('disable-dev-shm-usage')
    
    driver = webdriver.Chrome(chromeDriverPath, options=options)
    time.sleep(2)
    

def crawl_portal_notice():
    global driver
        
    # first, set chrome driver options
    try:
        set_chromedriver()
    except:
        # when exception occurs inside set_chromedriver()
        panic('set_chromedriver')
    
    # second, enter to portal notice page
    try:
        enter_portal_notice()
    except:
        # when exception not handled by try-except in enter_portal_notice() occurs 
        panic('enter_portal_notice')
    
    # third, get notice information up to 5 pages
    try:
        crawl()
    except DuplicateKeyError:
        # notice which is about to crawl is already in db
        pass
    except:
        # when exception not handled by try-except in crawl() occurs 
        panic('crawl')
        
    print('crawl_portal_notice fin')


if __name__ == '__main__':
    crawl_portal_notice()