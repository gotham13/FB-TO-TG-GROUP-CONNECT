import facebook
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import os
import json
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
mount_point=config.get('openshift','persistent_mount_point')
adminlist=str(config.get('telegram','admin_chat_id')).split(',')
send_to=str(config.get('telegram','send_to')).split(',')

graph = facebook.GraphAPI(access_token=Facebook_user_token, version="2.7")

exists=False
latest=None
if  os.path.exists(mount_point+'latest.json'):
    exists=True
    with open(mount_point+'latest.json', 'r') as latest1:
        latest = json.load(latest1)


sched = BackgroundScheduler()
@sched.scheduled_job('cron', second=20)
def fetch():
    global latest,exists
    bot = Bot(Telegram_bot_token)
    try:
        post = graph.get_object(id=Facebook_group_id, fields='feed')
        feeds = post['feed']['data']
        feed = feeds[0]
        latest_time_data = feed['updated_time']
        latest_time = {'latest': latest_time_data}
        with open(mount_point + 'latest.json', 'w') as latest1:
            json.dump(latest_time, latest1)
        if exists is False:
            if 'message' in feed and 'story' in feed:
                message = feed['story'] + "\n" + feed['message'] + "\n\nCheck it out here\n" + Facebook_group_url
                for chatids in send_to:
                    bot.send_message(chat_id=chatids, text=message)
            elif 'message' in feed:
                message = "Someone posted in the group:\n" + feed[
                    'message'] + "\n\nCheck it out here\n" + Facebook_group_url
                for chatids in send_to:
                    bot.send_message(chat_id=chatids, text=message)
            elif 'story' in feed:
                message = feed['story'] + "\n\nCheck it out here\n" + Facebook_group_url
                for chatids in send_to:
                    bot.send_message(chat_id=chatids, text=message)
        else:
            for i in range(0, len(feeds)):
                if feeds[i]['updated_time'] == latest['latest']:
                    break
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

        with open(mount_point + 'latest.json', 'r') as latest1:
            latest = json.load(latest1)
        exists = True
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

