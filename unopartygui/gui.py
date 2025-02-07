import logging
import json
import os
import platform
import sys
from decimal import Decimal as D

from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QVariant
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QUrl
from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QToolBar
from PyQt5.QtWidgets import QStackedWidget
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QMenuBar
from PyQt5.QtWidgets import QApplication
from PyQt5.QtQuick import QQuickView
from PyQt5.QtQml import QJSValue

from PyQt5 import QtWidgets, QtCore, QtGui

import unopartygui
from unopartygui.api import UnopartydAPI, UnopartydRPCError
from unopartygui.config import Config
from unopartycli.clientapi import ConfigurationError
from unopartylib.lib import log

from unopartygui import tr

logger = logging.getLogger(__name__)

CURR_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))

class MenuItem(QLabel):
    def __init__(self, text, parent=None):
        QLabel.__init__(self, parent)
        self.parent = parent
        self.setText(text)

    def activate(self):
        pluginIndex = self.property('pluginIndex')
        actionValue = self.property('actionValue')
        
        # change style
        if self.parent.currentMenuItem:
            self.parent.currentMenuItem.setProperty('active', 'false')
        self.setProperty('active', 'true')
        
        self.parent.refreshStyleSheet()
        self.parent.app.processEvents()
        if self.parent.currentMenuItem != self:
            self.parent.stackedWidget.hide()
        self.parent.currentMenuItem = self
        # display the plugin
        self.parent.stackedWidget.setCurrentIndex(pluginIndex)
        # call the plugin callback
        self.parent.app.processEvents()
        self.parent.plugins[pluginIndex].onMenuAction(actionValue)
        self.parent.stackedWidget.show()
        self.parent.refreshStyleSheet()

    def mouseReleaseEvent(self, event):
        self.activate()

class GUI(QMainWindow):

    def __init__(self, config, app, splash):
        super().__init__()

        self.config = config
        self.app = app
        self.splash = splash

        log.set_up(logger, verbose=config.VERBOSE, logfile=config.LOG_FILE)

        self.resize(1024, 680)
        self.setWindowTitle(tr("Unoparty GUI"))
        icon = QtGui.QIcon('assets/counterparty.icns')
        self.setWindowIcon(icon)
        self.app.setWindowIcon(icon)

        def openPreference():
            if self.config.initialize(openDialog=True):
                self.loadPlugins()

        # Add Preferences menu 
        mainMenuBar = QMenuBar()
        newAct = QAction(tr("Preferences..."), self)
        newAct.triggered.connect(openPreference)
        fileMenu = mainMenuBar.addMenu(tr("Unoparty GUI"))
        fileMenu.addAction(newAct)
        self.setMenuBar(mainMenuBar)

        self.currentBlock = None        
        if self.refreshStatus():
            self.loadPlugins()

            timer = QtCore.QTimer(self);
            timer.timeout.connect(self.refreshStatus)
            timer.start(self.config.POLL_INTERVAL)

            self.show()

    # init clientapi
    def initXcpApi(self):
        if hasattr(self, 'xcpApi') and isinstance(self.xcpApi, UnopartydAPI):
            return True
        else:
            try:
                self.xcpApi = UnopartydAPI(self.config)
                return True
            except ConfigurationError as e:
                self.show()
                msgBox = QMessageBox(self)
                msgBox.setText(str(e))
                msgBox.setModal(True)
                msgBox.show()
                return False

    def refreshStatus(self):
        if not self.initXcpApi():
            return False

        try:
            serverInfo = self.xcpApi.call({'method': 'get_running_info', 'params':[]}, return_dict=True)

            unopartyLastBlock = serverInfo['last_block']['block_index']
            walletLastBlock = self.xcpApi.call({'method': 'wallet_last_block', 'params':{}}, return_dict=True)

            message = 'Server Last Block: {} | Wallet Last Block: {}'

            self.statusBar().showMessage(message.format(unopartyLastBlock, walletLastBlock))

            if self.currentBlock is not None and self.currentBlock != unopartyLastBlock:
                self.notifyPlugins('new_block', {'block_index': unopartyLastBlock})

            self.currentBlock = unopartyLastBlock

            return True
        # TODO
        except Exception as e:
            # if application startup then open preference dialog and exit
            if not hasattr(self, 'plugins'):
                if self.splash:
                    self.splash.hide()
                self.config.initialize(openDialog=True)
                exit()
            # else fails silently, error are already shown by `api.UnopartydRPCError`
            # and refreshStatus is executed each self.config.POLL_INTERVAL second
            return False

    def notifyPlugins(self, messageName, messageData):
        logger.debug('Notify plugins `{}`: {}'.format(messageName, messageData))
        if hasattr(self, 'plugins'):
            for plugin in self.plugins:
                if hasattr(plugin, 'onMessage'):
                    plugin.onMessage(messageName, messageData)
            self.refreshToolbar()

    def refreshToolbar(self):
        pluginIndex = self.currentMenuItem.property('pluginIndex')
        actionValue = self.currentMenuItem.property('actionValue')
        self.initToolbar(selectedPluginIndex=pluginIndex, selectedActionValue=actionValue)
        self.currentMenuItem.setProperty('active', 'true')
        self.refreshStyleSheet()

    def initPlugins(self):
        # init QML plugin container
        if hasattr(self, 'stackedWidget'):
            del(self.stackedWidget)

        self.stackedWidget = QStackedWidget(self)
        self.plugins = []

        for pluginName in self.config.PLUGINS:
            view = QQuickView();
            view.setFlags(Qt.SubWindow)

            # add clientapi into the plugin context
            context = view.rootContext()

            context.setContextProperty('xcpApi', self.xcpApi)
            context.setContextProperty('GUI', self)

            # load plugin translations if i18n subfolder exists
            i18nDir = 'plugins/{}/i18n'.format(pluginName)
            if os.path.exists(i18nDir):
                translator = QtCore.QTranslator()
                fileName = 'send_'.format(QtCore.QLocale.system().name())
                #fileName = 'send_fr'
                translator.load(fileName, i18nDir)
                self.app.installTranslator(translator)

            # load QML file
            plugin_index_path = 'plugins/{}/index.qml'.format(pluginName)
            view.setSource(QUrl(plugin_index_path))
            
            plugin = view.rootObject()
            self.plugins.append(plugin)

            # call plugin init callback
            plugin.init()

            # add the plugin in the container
            container = QWidget.createWindowContainer(view, self)
            self.stackedWidget.addWidget(container)

    def initToolbar(self, selectedPluginIndex=None, selectedActionValue=None):
        # init toolbar
        if hasattr(self, 'toolbar'):
            self.removeToolBar(self.toolbar)
            del(self.toolbar)
            
        self.toolbar = QToolBar()
        self.toolbar.setAutoFillBackground(True);
        self.toolbar.setObjectName('menu')
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon|Qt.AlignLeft)
        self.addToolBar(Qt.LeftToolBarArea, self.toolbar)
        self.currentMenuItem = None

        pluginIndex = 0
        for plugin in self.plugins:
            # generate the left menu
            menu = plugin.property('menu')
            if isinstance(menu, QJSValue):
                menu = menu.toVariant()
            if menu and isinstance(menu, dict) and 'items' in menu and isinstance(menu['items'], list):
                # menu title
                if 'groupLabel' in menu:
                    menuGroupLabel = QLabel(menu['groupLabel'])
                    menuGroupLabel.setProperty('isGroupLabel', 'true')
                    self.toolbar.addWidget(menuGroupLabel)
                # menu item
                items = []
                for menuItem in menu['items']:
                    if isinstance(menuItem, dict) and 'label' in menuItem  and 'value' in menuItem:
                        items.append(MenuItem(menuItem['label'], self))
                        items[-1].setProperty('pluginIndex', pluginIndex)
                        items[-1].setProperty('actionValue', menuItem['value'])
                        items[-1].setProperty('isAction', 'true') 
                        self.toolbar.addWidget(items[-1])
                        if self.currentMenuItem is None or (selectedPluginIndex == pluginIndex and selectedActionValue == menuItem['value']):
                            self.currentMenuItem = items[-1]

            pluginIndex += 1

        self.currentMenuItem.activate()

    def loadPlugins(self):
        if not self.initXcpApi():
            return

        self.initPlugins()
        self.initToolbar()

        # display the plugin container
        self.refreshStyleSheet()
        self.setCentralWidget(self.stackedWidget)

    def refreshStyleSheet(self):
        self.setStyleSheet('''
            QWidget, QQuickView, QToolBar, QMainWindow { font-size:14pt }
            QToolBar#menu { background-color: #ececec; border: 1px solid #ececec; border-right-color: #000; }
            QToolBar#menu QLabel { width:100%; text-align:left; padding:3px; margin:0; }
            QToolBar#menu QLabel[isAction="true"]:hover { background-color:#CCC; }
            QToolBar#menu QLabel[active="true"] { background-color:#CCC; }
            QToolBar#menu QLabel[isAction="true"] { padding-left: 15px; }
            QToolBar#menu QLabel[isGroupLabel="true"] { color:#888888; text-transform:uppercase; }
        ''')

    # used in QML to display a confirm dialog
    @pyqtSlot(QVariant, QVariant, result=QVariant)
    def confirm(self, title, text):
        result = QMessageBox.question(self, title, text)
        if result == QMessageBox.Yes:
            return True
        else:
            return False

    # used in QML to display a message dialog
    @pyqtSlot(QVariant, QVariant)
    def alert(self, title, text):
        QMessageBox.information(self, title, text)

    @pyqtSlot(QVariant)
    def copyToClipboard(self, text):
        clipboard = QApplication.clipboard();
        clipboard.setText(text)
        
def main():
    app = QApplication(sys.argv)

    if platform.system() == "Windows":
        import ctypes
        appid = 'unoparty.unoparty-gui' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(appid)
    
    # load global translation
    translator = QtCore.QTranslator()
    fileName = 'unopartygui_'.format(QtCore.QLocale.system().name())
    #fileName = 'unopartygui_fr'
    translator.load(fileName, 'i18n')
    app.installTranslator(translator)

    splash_pix = QtGui.QPixmap('assets/splash.png')
    splash = QtWidgets.QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setMask(splash_pix.mask())
    splash.show()
    splash.showMessage(tr("Loading wallet..."), Qt.AlignBottom | Qt.AlignHCenter);
    setattr(unopartygui, 'splash', splash)
    app.processEvents()

    config = Config(splash=splash)
    screen = GUI(config, app, splash)

    def quitApp():
        sys.exit()

    app.aboutToQuit.connect(quitApp)

    splash.finish(screen)
    app.exec()

