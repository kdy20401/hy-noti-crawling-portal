import sys
from pymongo import MongoClient, ASCENDING


def connect_db(board):
    password = sys.argv[2]
    client = MongoClient('mongodb+srv://kdy20401:{}@cluster0.vcl3w.mongodb.net/hynoti?retryWrites=true&w=majority'.format(password))
    
    if board == 'portal':
        collection = client.notice.portal_notice
    elif board == 'cse':
        collection = client.notice.cse_notice
    elif board == 'bs':
        collection = client.notice.bs_notice
    elif board == 'me':
        collection = client.notice.me_notice

    collection.create_index('title', name='unique_title', unique=True)
    return client, collection


def truncate_db(board, max_docs):
    client, collection = connect_db(board)
    n = collection.estimated_document_count()
    
    if n > max_docs:
        for docs in collection.find({}).sort('date', ASCENDING).limit(n - max_docs):
            _id = docs['_id']
            collection.delete_one({'_id':_id})
            
    client.close()


def truncate_db_all():
    truncate_db('portal', 300)
    truncate_db('cse', 30)
    truncate_db('bs', 30)
    truncate_db('me', 30)