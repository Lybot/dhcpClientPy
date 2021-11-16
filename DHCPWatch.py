import subprocess as sp  # модуль для взаимодействия с терминалом
import time as t  # модуль для работы со временем
import re  # модуль для работы с регулярными выражениями

veth_arr = {'0': '192.168.0.1'}

log_fname = "/var/lib/dhcp/dhcpWatcher/logs"  # путь к файлу логов
# в логах отображается состояние dhcpWatcher:
# 1) INITIAL DHCP's IP is [DHCP SERVER's IP address] -
#	отображает IP адрес DHCP сервера полученный при запуске dhcpWatcher
# 	из файла dhclient.leases
# 2) DHCPserver is LOST - DHCP сервер выполнил переход на другой IP
# 3) DHClient RESTARTED - DHCP клиент перезапущен
# 4) NEW DHCP IP [new IP] - новый IP адрес DHCP сервера

##########################################################################

leases_fname = "/var/lib/dhcp/dhclient.leases"  # путь к файлу данных dhcp аренды
# функция чтения IP адреса DHCP сервера из файла leases_fname
def get_dhcp_ip(fname):
    f = open(fname, 'r')
    leases = str(f.read())
    try:
        dhcp_ip_addr = re.findall(r'dhcp-server-identifier (.*);', leases)[-1]
    except:
        dhcp_ip_addr = "192.168.0.1"
    f.close()
    return dhcp_ip_addr

# функция записи в файл логов

def log(s):  # s - записываемая строка
    try:
        f = open(log_fname, 'a')
        t_stamp = t.strftime("%d-%m-%Y %H:%M:%S \t", t.gmtime(t.time()))
        s = t_stamp + s + "\n"  # добавляем временную метку перед записью
        f.write(s)
        f.close()
        print(s)
    except:
        print(s)

# функция выполнения команды в оболочке

def exec_com(command_string):
    p = sp.Popen(command_string, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
    out, err = str(p.stdout.read()), str(p.stderr.read())
    return out, err  # возвращает вывод оболочки и ошибку


def get_veth_ip(num):
    cmd = "ifconfig eth0:" + num
    ifcfg_out = exec_com(cmd)[0]
    veth_ip = re.findall(r'(\d+\.\d+\.\d+\.\d+)', ifcfg_out)[0]
    return veth_ip


##########################################################################
# Инициализация
log("INITIALIZATION...")
log("Getting last DHCP server's IP...")
# читаем IP адрес DHCP сервера, записываем в переменную dhcp_ip_addr
dhcp_ip_addr = get_dhcp_ip(leases_fname)
# записываем в лог начальный адрес DHCP сервера
log_str = "[ + ] DHCP's IP is " + dhcp_ip_addr
log(log_str)
log("Setting iptables rules...")
iptables_err = exec_com("iptables -C OUTPUT -s 192.168.0.1/24 -j DROP")[1]
if "Bad rule" in iptables_err:
    exec_com("iptables -A OUTPUT -s 192.168.0.1/24 -j DROP")
    log("[ + ] Iptables rule OUTPUT -s 192.168.0.1/24 -j DROP is set.")

iptables_err = exec_com("iptables -C INPUT -d 192.168.0.1/24 -j DROP")[1]
if "Bad rule" in iptables_err:
    exec_com("iptables -A INPUT -d 192.168.0.1/24 -j DROP")
    log("[ + ] Iptables rule INPUT -d 192.168.0.1/24 -j DROP is set.")
log("Setting ethernet interfaces")
t.sleep(10)
exec_com("ifconfig eth0 192.168.0.1/24")
t.sleep(1)
exec_com("ifconfig eth0:0 192.168.0.2/24")
t.sleep(1)
t.sleep(5)
exec_com("dhclient -v eth0:0")
exec_com("killall -9 dhclient")
t.sleep(1)
veth_arr['0'] = get_veth_ip('0')
log_str = "[ + ] Ethernet interfaces are set. Eth0:0 has IP " + veth_arr['0']
ifcfg_out = veth_arr['0'] #в данной переменной хранится текущий ip-адрес порта, к которому закреплен dhcp
log(log_str)

# Основной цикл
while True:
    try:
        # выполняем ping DHCP сервера
        t.sleep(1)
        command = "ping " + str(dhcp_ip_addr) + " -c 1"
        ping_out = exec_com(command)[0]
        # извлекаем из вывода количество принятых от сервера ICMP пакетов
        pk_received = int(re.findall(r'(\d) received', ping_out)[-1])
        if pk_received < 1:  # если не принято ни одного пакет
            log("[ !!! ] DHCPserver is LOST")
            is_set_con = 0
            for key in veth_arr.items():
                cmd = "netstat -atn | grep " + str(key[1]) + " | grep ESTABLISHED | wc -l"
                cmd_out = exec_com(cmd)[0]
                set_con = int(re.findall(r'(\d+)', cmd_out)[-1])
                if set_con == 0:
                    cmd = "dhclient -v eth0:" + str(key[0])
                    exec_com("killall -9 dhclient")
                    dhcl_out = exec_com(cmd)[0]  # перезапускаем DHCP клиента
                    t.sleep(2)
                    dhcp_ip_addr = get_dhcp_ip(leases_fname)  # получаем новый адрес сервера
                    cmd = "ifconfig eth0:" + str(key[0])
                    ifcfg_out = exec_com(cmd)[0]
                    veth_arr[key[0]] = re.findall(r'(\d+\.\d+\.\d+\.\d+)', ifcfg_out)[0] #записываем новый адрес хоста в массив
                    ifcfg_out = veth_arr[key[0]]
                    log_str = "[ + ] DHClient RESTARTED. Eth0:{0}/DHCP - {1}/{2}".format(key[0], ifcfg_out, dhcp_ip_addr)
                    log(log_str)
                    is_set_con += 1
                    break
            if is_set_con==0: # если нет свободных портов, то выполняется следующий алгоритм
                number_eth = '0'
                for i in range(65000): # цикл для выбора номера нового виртуального интерфейса
                    if i>veth_arr.__len__()+1: # если количество созданных виртуальных портов меньше итератора, то выход из цикла
                        break
                    if not str(i) in veth_arr: # если данный номер интерфейса не задействован, то запоминаем его
                        number_eth = str(i)
                        log(number_eth+" not in mass")
                        break
                eth = "eth0:"+ number_eth
                log('Start new eth {0}'.format(eth))
                cmd = "ifconfig " + eth + " 192.168.0."+str(veth_arr.__sizeof__()+3)+"/24" # создаем новый интерфейс с определенным до этого номером
                exec_com(cmd)
                cmd = "dhclient -v eth0:" + number_eth # прикрепляем к данному порту dhcp-клиент
                exec_com(cmd)
                exec_com("killall -9 dhclient")
                dhcp_ip_addr = get_dhcp_ip(leases_fname)
                cmd = "ifconfig eth0:" + number_eth
                ifcfg_out = exec_com(cmd)[0] # получаем новый ip-адрес
                veth_arr[number_eth] = re.findall(r'(\d+\.\d+\.\d+\.\d+)', ifcfg_out)[0] # записываем новый ip-адрес в словарь используемых адресов в данный момент
                ifcfg_out = veth_arr[number_eth]
        if veth_arr.__len__() > 1: # данное условие необходимо для удаления неиспользуемых виртуальных интерфейсов
            for key in veth_arr.items():
                if key[1] != ifcfg_out: # прикреплен ли к данному интерфейсу dhcp клиент
                    cmd = "netstat -atn | grep " + str(key[1]) + " | grep ESTABLISHED | wc -l"
                    cmd_out = exec_com(cmd)[0]
                    set_con = int(re.findall(r'(\d+)', cmd_out)[-1]) # проверка на наличие соединений на данном интерфейса
                    if set_con ==0: # если соединений нет, то удаляем данный интерфейс
                        cmd = "ifconfig eth0:{0} down".format(key[0])
                        exec_com(cmd)
                        log("eth0:{0} was down".format(key[0]))
                        veth_arr.__delitem__(key[0]) # удаляем ip-адрес из словаря используемых адресов
        t.sleep(1)
    except:
        # в случае ошибки ждем 5 с, повторяем цикл сначала
        exec_com("dhclient -v eth0:0")
        # log("ERR")
        t.sleep(2)
        continue