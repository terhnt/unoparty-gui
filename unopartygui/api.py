import logging
import requests
import sys
import json
import time
from decimal import Decimal as D

from PyQt5.QtCore import QObject
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QVariant
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QMessageBox, QWidget, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtQml import QJSValue
from unopartycli import clientapi
from unopartycli.wallet import LockedWalletError
from unopartygui import tr
from unopartylib.lib import log
import unopartygui

logger = logging.getLogger(__name__)

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, D):
            return format(obj, '.8f')
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)

# TODO: display message box
class UnopartydRPCError(Exception):
    def __init__(self, message):
        if hasattr(unopartygui, 'splash'):
            unopartygui.splash.hide()
        super().__init__(message)
        msgBox = QMessageBox()
        msgBox.setText(message)
        msgBox.setModal(True)
        msgBox.exec()
        # TODO
        raise Exception(message)

class InputDialog(QDialog):
    def __init__(self, message, is_password=False, parent=None):
        super().__init__(parent) 

        self.message = message
        self.setModal(True)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        label = QLabel(message)
        self.layout.addWidget(label)
        self.input = QLineEdit()
        if is_password:
            self.input.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.input)

        def onOkPushed():
            self.close()

        okBtn = QPushButton(tr("Ok"))
        okBtn.clicked.connect(onOkPushed)
        self.layout.addWidget(okBtn)

        self.exec()

    def value(self):
        return self.input.text()

    @staticmethod
    def input(message, is_password=False):
        askValue = InputDialog(message, is_password=is_password)
        return askValue.value()

def pubkeyResolver(address):
    message = tr('Public keys (hexadecimal) or Private key (Wallet Import Format) for `{}`: ').format(address)
    return InputDialog.input(message=message)

class UnopartydAPI(QObject):
    def __init__(self, config):
        super(UnopartydAPI, self).__init__()
        clientapi.initialize(testnet=config.TESTNET, testcoin=False,
                            unoparty_rpc_connect=config.UNOPARTY_RPC_CONNECT, unoparty_rpc_port=config.UNOPARTY_RPC_PORT, 
                            unoparty_rpc_user=config.UNOPARTY_RPC_USER, unoparty_rpc_password=config.UNOPARTY_RPC_PASSWORD,
                            unoparty_rpc_ssl=config.UNOPARTY_RPC_SSL, unoparty_rpc_ssl_verify=config.UNOPARTY_RPC_SSL_VERIFY,
                            wallet_name=config.WALLET_NAME, wallet_connect=config.WALLET_CONNECT, wallet_port=config.WALLET_PORT, 
                            wallet_user=config.WALLET_USER, wallet_password=config.WALLET_PASSWORD,
                            wallet_ssl=config.WALLET_SSL, wallet_ssl_verify=config.WALLET_SSL_VERIFY,
                            requests_timeout=config.REQUESTS_TIMEOUT)
        log.set_up(logger, verbose=config.VERBOSE, logfile=config.LOG_FILE)

    @pyqtSlot(QVariant, result=QVariant)
    def call(self, query, return_dict=False):
        if isinstance(query, QJSValue):
            query = query.toVariant()
        # TODO: hack, find a real solution
        # logger.debug(query)
        try:
            for key in query['params']:
                if key in ['quantity']:
                    query['params'][key] = int(query['params'][key])
        except:
            pass

        try:
            result = clientapi.call(query['method'], query['params'], pubkey_resolver=pubkeyResolver)
        except LockedWalletError as e:
            passphrase = InputDialog.input(message=tr('Enter your wallet passhrase:'), is_password=True)
            try:
                clientapi.call('unlock', {'passphrase': passphrase})
                return self.call(query)
            except Exception as e:
                raise UnopartydRPCError(str(e))
        except Exception as e:
            raise UnopartydRPCError(str(e))
        
        # TODO: hack, find a real solution
        result = json.dumps(result, cls=DecimalEncoder)
        result = json.loads(result)

        #  logger.debug(result)
        if return_dict:
            return result
        return QVariant(result)
        
