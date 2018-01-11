import facebook
import os
import datetime
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import shutil
import time
from queue import Queue
from threading import Thread
from telegram import Bot
from configparser import ConfigParser
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Updater, Filters,ConversationHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# State of conversation handler
TOKEN,BDC=range(2)

config = ConfigParser()
config.read('config.ini')
mount_point=config.get('openshift','persistent_mount_point')

# CONNECTING TO SQLITE DATABASE AND CREATING TABLES
conn = sqlite3.connect(mount_point+'posts.db')
create_table_request_list = [
    'CREATE TABLE post_info(post_id TEXT PRIMARY KEY,message_ids TEXT,chat_ids TEXT,message_content TEXT)',
]
for create_table_request in create_table_request_list:
    try:
        conn.execute(create_table_request)
    except Exception:
        pass

# copying config.ini to persistent storage
if not os.path.exists(mount_point+'config.ini'):
    shutil.copy('config.ini',mount_point+'config.ini')

config.read(mount_point+'config.ini')
Facebook_user_token=config.get('facebook','user_access_token')
Telegram_bot_token=config.get('telegram','bot_token')
Facebook_group_id=config.get('facebook','group_id')
Facebook_group_url=config.get('facebook','group_url')
adminlist=str(config.get('telegram','admin_chat_id')).split(',')
send_to=str(config.get('telegram','send_to')).split(',')

graph = facebook.GraphAPI(access_token=Facebook_user_token, version="2.7")

conn.commit()
conn.close()

latest=None
sched = BackgroundScheduler()

'''
Making 11 api calls per execution in every 3:40 secs to prevent crossing api limit
Reduce the value of cmp to decrease the the interval such that api limit of 200 calls is not met
'''
# Configured such that to be under api limit 200 calls in 60 minutes"
@sched.scheduled_job('interval', minutes=3,seconds=40)
def fetch():
    '''
    fetches the feed of the group and checks for a new post.
    If a new post is present sends it to all ids in send_to.
    '''
    global latest
    bot = Bot(Telegram_bot_token)
    try:
        post = graph.get_object(id=Facebook_group_id, fields='feed')
        feeds = post['feed']['data']
        # Extracting the latest entry from feeds
        feed = feeds[0]
        # Fetching the updated_time field from latest entry and storing it temporarily
        latest_time_data = datetime.datetime.strptime(feed['updated_time'], '%Y-%m-%dT%H:%M:%S+%f')
        if latest is None:
            # The script has run for the first time
            # updating the value of latest to the updated_time field of the latest_time_data in field
            latest=latest_time_data
        else:
            # maximum no of posts to check for a new post from the first post in feed
            cmp=10
            if len(feeds)<10:
                cmp=len(feeds)
            for i in range(0, cmp):
                post_id=feeds[i]['id']
                # performing another request to fetch the creation_time entry of the feed
                creation=graph.get_object(id=post_id)['created_time']
                message = message_generater(feeds[i])
                if message is None:
                    continue
                # if the creation_time of the post is less than the updated_time of the latest post from the previous run
                # then it is not a new post
                if datetime.datetime.strptime(creation, '%Y-%m-%dT%H:%M:%S+%f') <= latest:
                    conn = sqlite3.connect(mount_point + 'posts.db')
                    c = conn.cursor()
                    # CHECKING WITH THE VALUE STORED IN DATABASE IF THERE HAS BEEN AN UPDATE
                    c.execute("SELECT message_ids,chat_ids,message_content FROM post_info WHERE post_id=?",(post_id,))
                    for row in c.fetchall():
                        if(message==row[2]):
                            continue
                        # IF THERE HAS BEEN AN UPDATE EDITING MESSAGE SENT TO TELEGRAM
                        message_id_list=row[0].split(',')
                        chat_id_list=row[1].split(',')
                        for a,b in zip(message_id_list,chat_id_list):
                            bot.edit_message_text(text=message,message_id=a,chat_id=b)
                            time.sleep(1)
                        c.execute("UPDATE post_info SET message_content=? WHERE post_id=?",(message,post_id))
                    conn.commit()
                    c.close()
                    conn.close()
                    continue
                message_ids = ""
                chat_ids = ""
                for chatids in send_to:
                    message_object = bot.send_message(chat_id=chatids, text=message)
                    message_ids = message_ids + str(message_object.message_id) + ","
                    chat_ids = chat_ids + str(chatids) + ","
                    time.sleep(1)
                message_ids = message_ids[:-1]
                chat_ids = chat_ids[:-1]
                conn = sqlite3.connect(mount_point + 'posts.db')
                c = conn.cursor()
                # INSERTING NEW POST INTO DATABASE
                c.execute(
                    "INSERT OR IGNORE INTO post_info (post_id,message_ids,chat_ids,message_content) VALUES (?,?,?,?)",
                    (str(post_id), str(message_ids), str(chat_ids), str(message)))
                conn.commit()
                c.close()
                conn.close()
            # updating the value of latest
            latest = latest_time_data
    except facebook.GraphAPIError:
        for chatids in adminlist:
            bot.send_message(chat_id=chatids, text="Your facebook user access token might have expired")
            time.sleep(1)
    except Exception as e:
        print(e)
        for chatids in adminlist:
            bot.send_message(chat_id=chatids, text="Some error is occuring\n"+str(e))
            time.sleep(1)

@sched.scheduled_job('interval',days=7)
def drop_table():
    try:
        conn = sqlite3.connect(mount_point + 'posts.db')
        c = conn.cursor()
        c.execute("DELETE FROM post_info")
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        print(e)

# FUNCTION TO GENERATE MESSAGE
def message_generater(feed):
    if 'message' in feed and 'story' in feed:
        message = feed['story'] + "\n" + feed[
            'message'] + "\n\nCheck it out here\n" + Facebook_group_url
        return message
    elif 'message' in feed:
        message = "Someone posted in the group:\n" + feed[
            'message'] + "\n\nCheck it out here\n" + Facebook_group_url
        return message
    elif 'story' in feed:
        if 'shared' in feed['story']:
            message = feed['story'] + "\n\nCheck it out here\n" + Facebook_group_url
            return message
    return None


def broadcast(bot,update):
    if not str(update.message.chat_id) in adminlist:
        update.message.reply_text("sorry you are not an admin")
        return ConversationHandler.END
    update.message.reply_text("Send your message")
    return BDC

def broadcast_message(bot,update):
    message = update.message.text
    for chatids in send_to:
        try:
            bot.send_message(text=message,chat_id=chatids)
        except:
            pass
        time.sleep(1)
    return ConversationHandler.END

# ADMIN CONVERSATION HANDLER TO BROADCAST MESSAGES
def change_token(bot, update):
    # Command handler for changing the token
    if str(update.message.chat_id) in adminlist:
        update.message.reply_text('Hi,please enter the new user access token')
        return TOKEN
    else:
        update.message.reply_text('Sorry you are not an admin')
        return ConversationHandler.END

def token(bot,update):
    global Facebook_user_token,graph
    new_token=update.message.text
    config['facebook']['user_access_token']=new_token
    with open(mount_point+'config.ini','w') as configfile:
        config.write(configfile)
    Facebook_user_token=new_token
    graph=facebook.GraphAPI(access_token=Facebook_user_token, version="2.7")
    update.message.reply_text("User access token changed")
    return ConversationHandler.END


def cancel(bot,update):
    update.message.reply_text("cancelled")
    return ConversationHandler.END

# FUNCTION FOR LOGGING ALL KINDS OF ERRORS
def error(bot, update, error):
    logger.warning('Update "%s" caused error "%s"' % (update, error))

# Setup functipon for python telegram bot
def setup(webhook_url=None):
    """If webhook_url is not passed, run with long-polling."""
    logging.basicConfig(level=logging.WARNING)
    if webhook_url:
        bot = Bot(Telegram_bot_token)
        update_queue = Queue()
        dp = Dispatcher(bot, update_queue)
    else:
        updater = Updater(Telegram_bot_token)
        bot = updater.bot
        dp = updater.dispatcher
        # ADMIN CONVERSATION HANDLER TO CHANGE TOKEN
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('change_token', change_token)],
            allow_reentry=True,
            states={
                TOKEN: [MessageHandler(Filters.text, token)]
            },

            fallbacks=[CommandHandler('cancel', cancel)]
        )
        # ADMIN CONVERSATION HANDLER TO BROADCAST MESSAGES
        conv_handler1 = ConversationHandler(
            entry_points=[CommandHandler('broadcast', broadcast)],
            allow_reentry=True,
            states={
                BDC: [MessageHandler(Filters.text, broadcast_message)]
            },

            fallbacks=[CommandHandler('cancel', cancel)]
        )
        sched.start()
        dp.add_handler(conv_handler)
        dp.add_handler(conv_handler1)
        # log all errors
        dp.add_error_handler(error)
    if webhook_url:
        bot.set_webhook(webhook_url=webhook_url)
        thread = Thread(target=dp.start, name='dispatcher')
        thread.start()
        return update_queue, bot
    else:
        bot.set_webhook()  # Delete webhook
        updater.start_polling()
        updater.idle()


if __name__ == '__main__':
    setup()

