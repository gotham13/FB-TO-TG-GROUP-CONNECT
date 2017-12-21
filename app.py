import facebook
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from queue import Queue
from threading import Thread
from telegram import Bot
from configparser import ConfigParser
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Updater, Filters,ConversationHandler


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN=range(1)
config = ConfigParser()
config.read('config.ini')
Facebook_user_token=config.get('facebook','user_access_token')
Telegram_bot_token=config.get('telegram','bot_token')
Facebook_group_id=config.get('facebook','group_id')
Facebook_group_url=config.get('facebook','group_url')
adminlist=str(config.get('telegram','admin_chat_id')).split(',')
send_to=str(config.get('telegram','send_to')).split(',')

graph = facebook.GraphAPI(access_token=Facebook_user_token, version="2.7")

latest=None
sched = BackgroundScheduler()
@sched.scheduled_job('interval', minutes=3,seconds=40) #change interval according to need we are making 11 api calls per execution and total limit is 200 calls per minute per total no of avg users
def fetch():
    global latest,already_posted
    bot = Bot(Telegram_bot_token)
    try:
        post = graph.get_object(id=Facebook_group_id, fields='feed')
        feeds = post['feed']['data']
        feed = feeds[0]
        latest_time_data = datetime.datetime.strptime(feed['updated_time'], '%Y-%m-%dT%H:%M:%S+%f')
        if latest is None:
            latest=latest_time_data
        else:
            cmp=10
            if len(feeds)<10:
                cmp=len(feeds)
            for i in range(0, cmp):
                creation=graph.get_object(id=feeds[i]['id'])['created_time']
                if datetime.datetime.strptime(creation, '%Y-%m-%dT%H:%M:%S+%f') <= latest:
                    continue
                if 'message' in feeds[i] and 'story' in feeds[i]:
                    message = feeds[i]['story'] + "\n" + feeds[i][
                        'message'] + "\n\nCheck it out here\n" + Facebook_group_url
                    for chatids in send_to:
                        bot.send_message(chat_id=chatids, text=message)
                elif 'message' in feeds[i]:
                    message = "Someone posted in the group:\n" + feeds[i][
                        'message'] + "\n\nCheck it out here\n" + Facebook_group_url
                    for chatids in send_to:
                        bot.send_message(chat_id=chatids, text=message)
                elif 'story' in feeds[i]:
                    message = feeds[i]['story'] + "\n\nCheck it out here\n" + Facebook_group_url
                    for chatids in send_to:
                        bot.send_message(chat_id=chatids, text=message)
            latest = latest_time_data
    except facebook.GraphAPIError:
        for chatids in adminlist:
            bot.send_message(chat_id=chatids, text="Your facebook user access token might have expired")
    except:
        for chatids in adminlist:
            bot.send_message(chat_id=chatids, text="Some error is occuring")


def change_token(bot, update):
    if update.message.chat_id not in adminlist:
        update.message.reply_text('Hi,please enter the new user access token')
        return TOKEN
    else:
        update.message.reply_text('Sorry you are not an admin')
        return ConversationHandler.END

def token(bot,update):
    global Facebook_user_token,graph
    new_token=update.message.text
    config['facebook']['user_access_token']=new_token
    with open('config.ini','w') as configfile:
        config.write(configfile)
    Facebook_user_token=new_token
    graph=facebook.GraphAPI(access_token=Facebook_user_token, version="2.7")
    update.message.reply_text("User access token changed")
    return ConversationHandler.END

def cancel(bot,update):
    update.message.reply_text("cancelled")
    return ConversationHandler.END

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
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('change_token', change_token)],
            allow_reentry=True,
            states={
                TOKEN: [MessageHandler(Filters.text, token)]
            },

            fallbacks=[CommandHandler('cancel', cancel)]
        )
        sched.start()
        dp.add_handler(conv_handler)

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

