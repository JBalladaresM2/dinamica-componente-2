# ==============================================================================
# SISTEMA WEB: DELIVERY SIMULATOR ("Déjenos de Semestre Eats")
# DINÁMICA UNIVERSITARIA DE ESTADÍSTICA: DISTRIBUCIÓN EXPONENCIAL
# ==============================================================================
#
# FLUJO AUTOMATIZADO Y SIMPLIFICADO:
# 1. Liberar Menú: Alumnos eligen su comida y esperan en "Orden en Cocina".
# 2. Iniciar Simulación en Ruta: 
#    - A los alumnos sin incidente se les entrega automáticamente al cumplir su X.
#    - A N alumnos elegidos aleatoriamente para incidente, se les activa la alerta de tráfico
#      de forma aleatoria dentro del rango [incident_min_s - incident_max_s] y esperan bloqueados.
# 3. Liberar Tráfico Escalonado:
#    - El admin libera el incidente. Los alumnos atrapados concluyen su entrega de forma
#      aleatoria y escalonada dentro del rango [stagger_release_max].
# ==============================================================================

import math
import random
import time
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'estadistica_exponencial_secret_key_2026'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=None)

# ------------------------------------------------------------------------------
# ESTRUCTURAS DE DATOS GLOBALES
# ------------------------------------------------------------------------------
clients = {}

system_state = {
    'lobby_open': False,          
    'lambda_param': 0.05,         
    'time_limit_x': 15.0,         
    'max_clients': 25,            
    'frozen_count': 5,            
    'incident_trigger_max': 12.0, # Rango para congelar / aparición de incidente (de 0.3s a incident_trigger_max)
    'stagger_release_max': 6.0,   # Rango para descongelar y completar entrega tras incidente
    'sim_start_time': None,       
    'current_phase': 1
}

# ------------------------------------------------------------------------------
# MÓDULO MATEMÁTICO (DISTRIBUCIÓN EXPONENCIAL)
# ------------------------------------------------------------------------------
def generate_exponential_time(lambda_rate):
    """
    x = -ln(1 - u) / lambda.
    Devuelve tiempo en segundos (min 0.3s, max 120s).
    """
    u = random.random()
    if u >= 0.999999:
        u = 0.999999
    x = -math.log(1.0 - u) / float(lambda_rate)
    return round(max(0.3, min(x, 120.0)), 2)


# ------------------------------------------------------------------------------
# CATÁLOGO DE INCIDENTES VIALES EN RUTA (VARIEDAD DE SITUACIONES)
# ------------------------------------------------------------------------------
INCIDENT_REASONS = [
    {
        'emoji': '🛸',
        'badge': 'ABDUCCIÓN OVNI',
        'title': '⚠️ ¡Repartidor abducido temporalmente por un OVNI!',
        'detail': 'Una nave extraterrestre elevó la moto con un rayo tractor para inspeccionar la comida.',
        'solved_badge': 'ALIENS SATISFECHOS',
        'solved_title': '¡Los alienígenas lo devolvieron a la Tierra! 👽🛸',
        'solved_detail': 'No encontraron vida inteligente, pero les olió muy rico la comida y soltaron la moto intacta.'
    },
    {
        'emoji': '⚡🚗',
        'badge': 'RASHO LÁSER',
        'title': '⚠️ ¡Un niño voló sobre mí y voló un auto con rasho láser!',
        'detail': 'El repartidor tuvo que esquivar un auto volador propulsado por un rasho láser en la avenida central.',
        'solved_badge': 'RASHO ESQUIVADO',
        'solved_title': '¡El auto con rasho láser pasó de largo! 🚗⚡',
        'solved_detail': 'El repartidor se cubrió tras una parada de autobús y continuó el trayecto ileso y a toda velocidad.'
    },
    {
        'emoji': '🏎️💨',
        'badge': 'LA FAMILIA',
        'title': '⚠️ ¡Se cruzó con Toretto en un semáforo en rojo!',
        'detail': 'Le dijeron que el tráfico no importa si le das la espalda a LA FAMILIA... y lo retaron a unos arrancones.',
        'solved_badge': 'POR LA FAMILIA',
        'solved_title': '¡Ganó la carrera usando nitro por LA FAMILIA! 🏎️🔥',
        'solved_detail': 'Toretto reconoció sus habilidades al volante y le abrió paso por el carril de alta velocidad.'
    },
    {
        'emoji': '🦖🦍',
        'badge': 'TITANES VIALES',
        'title': '⚠️ ¡Godzilla y King Kong peleando en la esquina!',
        'detail': 'Un lagarto gigante y un mono colosal están debatiendo quién invita los tacos en el centro de la ciudad.',
        'solved_badge': 'TITANES CALMADOS',
        'solved_title': '¡Los titanes hicieron las paces y abrieron paso! 🦖🤝🦍',
        'solved_detail': 'Decidieron pedir por Déjenos de Semestre Eats también, así que la calle quedó totalmente despejada.'
    },
    {
        'emoji': '🕸️',
        'badge': 'MULTIVERSO VIAL',
        'title': '⚠️ ¡Se encontró con otros 3 repartidores idénticos!',
        'detail': 'Un fallo en el multiverso provocó que varios repartidores idénticos se señalaran entre sí en una glorieta.',
        'solved_badge': 'CANON RESTAURADO',
        'solved_title': '¡El canon multiversal se restauró con éxito! 🕸️✨',
        'solved_detail': 'Cada quien regresó a su dimensión y tu repartidor retomó la ruta hacia tu aula a tiempo.'
    },
    {
        'emoji': '🚧',
        'badge': 'EMBOTELLAMIENTO',
        'title': '⚠️ Tráfico denso reportado en ruta',
        'detail': 'Un choque en la avenida principal ha detenido la circulación temporalmente.',
        'solved_badge': 'TRÁFICO SUPERADO',
        'solved_title': 'Tu pedido ha superado el tráfico 🎉',
        'solved_detail': 'La vía fue despejada y el repartidor aceleró el paso con éxito.'
    },
    {
        'emoji': '⚽',
        'badge': 'MUNDIAL 2026',
        'title': '⚠️ Enner Valencia le pego un balonazo al repartidor y no al arco.',
        'detail': 'El repartidor quedo inconciente.',
        'solved_badge': 'CONCIENCIA RECUPERADA',
        'solved_title': 'El repartidor reacciono 👍!',
        'solved_detail': 'El repartidor continuó el trayecto ileso y a toda velocidad.'
    }
]

# ------------------------------------------------------------------------------
# SUPERVISIÓN AUTOMÁTICA DE TIEMPOS EN VIVO E INCIDENTES
# ------------------------------------------------------------------------------
def active_monitor_loop(run_id):
    print(f"[Monitor En Vivo] Tarea de monitoreo iniciada para sim_start_time={run_id}")
    while system_state.get('sim_start_time') == run_id and system_state['current_phase'] in [3, 4]:
        socketio.sleep(0.3)
        try:
            current_time = time.time()
            elapsed_global = current_time - run_id
            updated_any = False
            
            lambda_val = system_state['lambda_param']
            threshold_x = system_state['time_limit_x']
            
            for cid, client in list(clients.items()):
                if client['status'] == 'simulation_running':
                    # 1. Si el alumno fue designado para tener un incidente en ruta
                    if client.get('will_have_incident') and not client.get('is_frozen'):
                        inc_trigger = client.get('incident_trigger_time', 10.0)
                        if elapsed_global >= inc_trigger:
                            client['is_frozen'] = True
                            client['status'] = 'phase4_freidora' # Incidencia en Tráfico / Ruta
                            client['freidora_start_time'] = current_time
                            updated_any = True
                            
                            if client.get('socket_id'):
                                socketio.emit('state_change', {
                                    'state': 'phase4_freidora',
                                    'product_name': client['product_name'] or '🍟 Papas Finitas (Estocástica Fries)',
                                    'freidora_start_time': current_time,
                                    'incident_info': client.get('incident_info', INCIDENT_REASONS[0])
                                }, room=client['socket_id'], namespace='/')
                            print(f"[Incidente Automático] Alumno '{client['name']}' atrapado en incidente ({client.get('incident_info', {}).get('badge', 'TRÁFICO')}) al seg {round(elapsed_global, 1)}s.")
                            
                    # 2. Si el alumno NO tiene incidente (o ya se cumplió), evaluamos si ya llegó su tiempo de entrega normal acotado
                    elif not client.get('is_frozen'):
                        effective_delivery_sec = min(client['time_x'], threshold_x + 5.0)
                        if elapsed_global >= effective_delivery_sec:
                            is_on_time = (client['time_x'] <= threshold_x)
                            final_status = 'phase3_ontime' if is_on_time else 'phase3_late'
                            client['status'] = final_status
                            client['delivered_time'] = round(elapsed_global, 1)
                            updated_any = True
                            
                            if client.get('socket_id'):
                                socketio.emit('state_change', {
                                    'state': final_status,
                                    'student_name': client['name'],
                                    'product_name': client['product_name'] or '🍔 La Semestre-Killer',
                                    'time_x': client['time_x'],
                                    'threshold_x': threshold_x
                                }, room=client['socket_id'], namespace='/')
                            print(f"[Entrega Normal] Alumno '{client['name']}' entregado en seg {round(elapsed_global, 1)}s -> {final_status}")
                            
            # 3. Evaluar si absolutamente todos los clientes ya terminaron para pasar automáticamente a la Fase 5 (Finalizado)
            if system_state['current_phase'] in [3, 4] and len(clients) > 0:
                all_finished = all(c['status'] in ['phase3_ontime', 'phase3_late', 'success_final'] for c in clients.values())
                if all_finished:
                    system_state['current_phase'] = 5
                    updated_any = True
                    print("[Dinámica Finalizada] Todos los clientes han completado sus fases.")

            if updated_any:
                broadcast_admin_update()
        except Exception as e:
            print(f"[Monitor Error] {e}")


# ------------------------------------------------------------------------------
# LIBERACIÓN ESCALONADA TRAS INCIDENTE EN TRÁFICO
# ------------------------------------------------------------------------------
def release_traffic_staggered_task(frozen_cids, waiting_cids, max_delay):
    schedule = []
    
    for cid in frozen_cids:
        d = round(random.uniform(0.3, max_delay), 2)
        schedule.append((d, cid, 'success_final'))
        
    for cid in waiting_cids:
        d = round(random.uniform(0.3, max_delay), 2)
        schedule.append((d, cid, 'normal_finish'))
        
    schedule.sort(key=lambda x: x[0])
    
    last_time = 0.0
    for delay_time, cid, action_type in schedule:
        sleep_dur = max(0.05, delay_time - last_time)
        socketio.sleep(sleep_dur)
        last_time = delay_time
        
        if cid in clients:
            current_elapsed = round(time.time() - system_state['sim_start_time'], 1) if system_state['sim_start_time'] else round(delay_time, 1)
            
            if action_type == 'success_final':
                clients[cid]['is_frozen'] = False
                clients[cid]['status'] = 'success_final'
                clients[cid]['delivered_time'] = current_elapsed
                is_late = current_elapsed > system_state['time_limit_x']
                if clients[cid].get('socket_id'):
                    socketio.emit('state_change', {
                        'state': 'success_final',
                        'student_name': clients[cid]['name'],
                        'product_name': clients[cid]['product_name'] or '🍟 Papas Finitas (Estocástica Fries)',
                        'time_x': clients[cid]['time_x'],
                        'delivered_time': current_elapsed,
                        'threshold_x': system_state['time_limit_x'],
                        'is_late': is_late,
                        'incident_info': clients[cid].get('incident_info', INCIDENT_REASONS[0])
                    }, room=clients[cid]['socket_id'], namespace='/')
            elif action_type == 'normal_finish':
                if clients[cid]['status'] == 'simulation_running':
                    is_on_time = (clients[cid]['time_x'] <= system_state['time_limit_x'])
                    final_st = 'phase3_ontime' if is_on_time else 'phase3_late'
                    clients[cid]['status'] = final_st
                    clients[cid]['delivered_time'] = current_elapsed
                    if clients[cid].get('socket_id'):
                        socketio.emit('state_change', {
                            'state': final_st,
                            'student_name': clients[cid]['name'],
                            'product_name': clients[cid]['product_name'] or '🍔 La Semestre-Killer',
                            'time_x': clients[cid]['time_x'],
                            'threshold_x': system_state['time_limit_x']
                        }, room=clients[cid]['socket_id'], namespace='/')
                    
            broadcast_admin_update()


# ------------------------------------------------------------------------------
# RUTAS HTTP
# ------------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/client')
def client_app():
    return render_template('client.html')

@app.route('/imgs/<path:filename>')
@app.route('/templates/imgs/<path:filename>')
def serve_imgs(filename):
    import os
    from flask import send_from_directory
    return send_from_directory(os.path.join(app.root_path, 'templates', 'imgs'), filename)

@app.route('/sounds/<path:filename>')
@app.route('/templates/sounds/<path:filename>')
def serve_sounds(filename):
    import os
    from flask import send_from_directory
    return send_from_directory(os.path.join(app.root_path, 'templates', 'sounds'), filename)


# ------------------------------------------------------------------------------
# EVENTOS SOCKETIO (SINCRONIZACIÓN DE DATOS)
# ------------------------------------------------------------------------------
def broadcast_admin_update():
    total_connected = len(clients)
    
    clients_list = []
    for cid, c in clients.items():
        sock_id = c.get('socket_id')
        clients_list.append({
            'socket_id': sock_id[:8] + '...' if sock_id else 'OFFLINE',
            'full_sid': sock_id or '',
            'name': c['name'],
            'product_name': c['product_name'] or 'Sin elegir',
            'status': c['status'],
            'time_x': c['time_x'],
            'delivered_time': c.get('delivered_time', None),
            'is_frozen': c['is_frozen'],
            'will_have_incident': c.get('will_have_incident', False),
            'incident_trigger_time': c.get('incident_trigger_time', None),
            'incident_info': c.get('incident_info', None),
            'is_late': (c.get('delivered_time', 0) > system_state['time_limit_x']) if c.get('delivered_time') else (c['time_x'] > system_state['time_limit_x'])
        })
        
    clients_list.sort(key=lambda x: x['name'].lower() if x['name'] else '')
    
    lambda_val = float(system_state['lambda_param'])
    limit_x = float(system_state['time_limit_x'])
    max_cls = int(system_state['max_clients'])
    
    prob_ontime = (1.0 - math.exp(-lambda_val * limit_x)) * 100.0 if lambda_val > 0 else 0.0
    expected_ontime_max = round((prob_ontime / 100.0) * max_cls)
    expected_late_max = max_cls - expected_ontime_max
    
    expected_ontime_active = round((prob_ontime / 100.0) * total_connected) if total_connected > 0 else 0
    expected_late_active = total_connected - expected_ontime_active if total_connected > 0 else 0
    
    elapsed_sim = round(time.time() - system_state['sim_start_time'], 1) if system_state['sim_start_time'] else 0.0
    
    socketio.emit('admin_data_sync', {
        'current_phase': system_state['current_phase'],
        'total_connected': total_connected,
        'max_clients': max_cls,
        'frozen_count': system_state['frozen_count'],
        'incident_trigger_max': system_state['incident_trigger_max'],
        'stagger_release_max': system_state['stagger_release_max'],
        'lambda_param': lambda_val,
        'time_limit_x': limit_x,
        'prob_ontime_percent': round(prob_ontime, 2),
        'prob_late_percent': round(100.0 - prob_ontime, 2),
        'expected_ontime_max': expected_ontime_max,
        'expected_late_max': expected_late_max,
        'expected_ontime_active': expected_ontime_active,
        'expected_late_active': expected_late_active,
        'sim_start_time': system_state['sim_start_time'],
        'elapsed_sim_time': elapsed_sim,
        'expected_value': round(1.0 / lambda_val, 2) if lambda_val > 0 else 0,
        'lobby_open': system_state['lobby_open'],
        'clients': clients_list
    }, room='admin', namespace='/')


@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    disconnected_cid = None
    for cid, c in list(clients.items()):
        if c.get('socket_id') == sid:
            c['socket_id'] = None
            c['is_online'] = False
            disconnected_cid = cid
            break
            
    broadcast_admin_update()
    
    if disconnected_cid:
        def check_reconnect():
            socketio.sleep(10)
            if disconnected_cid in clients and not clients[disconnected_cid].get('is_online'):
                del clients[disconnected_cid]
                broadcast_admin_update()
                print(f"[Sistema] Cliente {disconnected_cid} eliminado por inactividad tras desconexión.")
                
        socketio.start_background_task(check_reconnect)

@socketio.on('join_admin')
def handle_join_admin():
    join_room('admin')
    broadcast_admin_update()

@socketio.on('student_login')
def handle_student_login(data):
    sid = request.sid
    client_id = data.get('client_id')
    student_name = data.get('name', '').strip() or f"Usuario_{sid[:4]}"
        
    if client_id in clients:
        clients[client_id]['socket_id'] = sid
        clients[client_id]['is_online'] = True
        emit('state_change', {
            'state': clients[client_id]['status'],
            'student_name': clients[client_id]['name'],
            'product_name': clients[client_id]['product_name'],
            'time_x': clients[client_id]['time_x'],
            'delivered_time': clients[client_id].get('delivered_time'),
            'incident_info': clients[client_id].get('incident_info'),
            'lobby_open': system_state['lobby_open'],
            'sim_start_time': system_state['sim_start_time']
        })
        broadcast_admin_update()
        return

    max_limit = system_state['max_clients']
    if len(clients) >= max_limit:
        emit('room_full_event', {
            'title': 'Restaurantes Saturados',
            'message': f'Capacidad máxima alcanzada ({max_limit} usuarios).'
        })
        return

    initial_status = 'menu' if system_state['lobby_open'] else 'lobby'
    
    clients[client_id] = {
        'client_id': client_id,
        'socket_id': sid,
        'is_online': True,
        'name': student_name,
        'product': None,
        'product_name': None,
        'status': initial_status,
        'time_x': 0.0,
        'start_time': None,
        'is_frozen': False,
        'will_have_incident': False,
        'incident_trigger_time': None,
        'freidora_start_time': None,
        'delivered_time': None
    }
    
    emit('state_change', {
        'state': initial_status,
        'student_name': student_name,
        'lobby_open': system_state['lobby_open']
    })
    broadcast_admin_update()


# ------------------------------------------------------------------------------
# CONTROL DE FASES SIMPLIFICADO (PASO 1, PASO 2, PASO 3)
# ------------------------------------------------------------------------------
@socketio.on('admin_phase1_release_menu')
def handle_admin_phase1_release_menu():
    system_state['lobby_open'] = True
    system_state['current_phase'] = 1
    for cid, client in list(clients.items()):
        if client['status'] in ['lobby', 'menu']:
            if client.get('is_bot'):
                client['product'] = 'bot_burger'
                client['product_name'] = '🍔 Bot Burger'
                client['status'] = 'kitchen_waiting'
                client['time_x'] = generate_exponential_time(system_state['lambda_param'])
            else:
                client['status'] = 'menu'
                if client.get('socket_id'):
                    socketio.emit('state_change', {'state': 'menu'}, room=client['socket_id'], namespace='/')
    broadcast_admin_update()

@socketio.on('client_select_product')
def handle_client_select_product(data):
    client_id = data.get('client_id')
    if not client_id or client_id not in clients:
        return
    product_id = data.get('product_id')
    product_name = data.get('product_name', 'La Semestre-Killer')
    product_emoji = data.get('product_emoji', '🍔')
    
    time_x = generate_exponential_time(system_state['lambda_param'])
    clients[client_id]['product'] = product_id
    clients[client_id]['product_name'] = f"{product_emoji} {product_name}"
    clients[client_id]['status'] = 'kitchen_waiting'
    clients[client_id]['time_x'] = time_x
    
    emit('state_change', {'state': 'kitchen_waiting', 'product_name': clients[client_id]['product_name']})
    broadcast_admin_update()

@socketio.on('admin_phase3_run_simulation')
def handle_admin_phase3_run_simulation():
    """
    Paso 2: Iniciar Simulación en Ruta.
    Arranca el reloj. Selecciona de forma aleatoria quiénes tendrán incidente en ruta
    y les asigna el segundo exacto (entre incident_min_s y incident_max_s) en que aparecerá.
    Los demás se entregan solos al llegar a su tiempo X.
    """
    system_state['current_phase'] = 3
    system_state['sim_start_time'] = time.time()
    lambda_val = system_state['lambda_param']
    
    active_candidates = [cid for cid, c in clients.items() if c['status'] in ['phase2_challenge', 'kitchen_waiting', 'menu', 'lobby']]
    target_incidents = system_state['frozen_count']
    actual_incidents = min(target_incidents, len(active_candidates)) if active_candidates else 0
    chosen_for_incident = set(random.sample(active_candidates, actual_incidents)) if actual_incidents > 0 else set()
    
    max_inc = float(system_state.get('incident_trigger_max', 12.0))
    
    count = 0
    for cid, client in list(clients.items()):
        if cid in active_candidates:
            # SIEMPRE recalculamos time_x con el lambda activo de la simulación exacto en este instante
            client['time_x'] = generate_exponential_time(lambda_val)
                
            client['status'] = 'simulation_running'
            client['is_frozen'] = False
            client['delivered_time'] = None
            
            if cid in chosen_for_incident:
                client['will_have_incident'] = True
                client['incident_info'] = random.choice(INCIDENT_REASONS)
                trig_time = round(random.uniform(0.3, max_inc), 1)
                if client['time_x'] <= trig_time:
                    trig_time = round(max(0.5, client['time_x'] - 1.5), 1)
                client['incident_trigger_time'] = trig_time
            else:
                client['will_have_incident'] = False
                client['incident_trigger_time'] = None
                client['incident_info'] = None
                
            if client.get('socket_id'):
                socketio.emit('state_change', {
                    'state': 'simulation_running',
                    'student_name': client['name'],
                    'product_name': client['product_name'] or '🍔 La Semestre-Killer',
                    'time_x': client['time_x'],
                    'sim_start_time': system_state['sim_start_time']
                }, room=client['socket_id'], namespace='/')
            count += 1
            
    # Lanzar tarea de monitoreo en segundo plano dedicada exclusivamente a esta corrida
    socketio.start_background_task(active_monitor_loop, system_state['sim_start_time'])
            
    emit('admin_notification', {
        'type': 'success', 
        'message': f'¡Repartidores en ruta hacia {count} alumnos! ({len(chosen_for_incident)} de ellos sufrirán incidente vial en un máx de {max_inc}s).'
    })
    broadcast_admin_update()

@socketio.on('admin_phase4_release_freidora')
def handle_admin_phase4_release_freidora():
    """
    Paso 3: Liberar Tráfico y Descongelar Escalonado.
    """
    system_state['current_phase'] = 4
    frozen_cids = [cid for cid, c in clients.items() if c['status'] == 'phase4_freidora' or c['is_frozen']]
    waiting_cids = [cid for cid, c in clients.items() if c['status'] == 'simulation_running' and not c['is_frozen']]
    max_d = float(system_state.get('stagger_release_max', 6.0))
    
    socketio.start_background_task(release_traffic_staggered_task, frozen_cids, waiting_cids, max_d)
    total_count = len(frozen_cids) + len(waiting_cids)
    emit('admin_notification', {'type': 'success', 'message': f'Resolución escalonada en marcha ({total_count} alumnos en total).'})
    broadcast_admin_update()


# ------------------------------------------------------------------------------
# CONFIGURACIÓN Y REINICIO
# ------------------------------------------------------------------------------
@socketio.on('admin_update_config')
def handle_admin_update_config(data):
    try:
        if 'lambda_param' in data and data['lambda_param'] is not None:
            val = float(data['lambda_param'])
            if val > 0.0001:
                system_state['lambda_param'] = round(val, 5)
                
        if 'time_limit_x' in data and data['time_limit_x'] is not None:
            val = float(data['time_limit_x'])
            if val > 0.1:
                system_state['time_limit_x'] = round(val, 2)
                
        if 'max_clients' in data and data['max_clients'] is not None:
            val = int(data['max_clients'])
            if val >= 1:
                system_state['max_clients'] = val
                
        if 'frozen_count' in data and data['frozen_count'] is not None:
            val = int(data['frozen_count'])
            if val >= 0:
                system_state['frozen_count'] = val

        if 'incident_trigger_max' in data and data['incident_trigger_max'] is not None:
            val = float(data['incident_trigger_max'])
            if val >= 0.5:
                system_state['incident_trigger_max'] = round(val, 1)

        if 'stagger_release_max' in data and data['stagger_release_max'] is not None:
            val = float(data['stagger_release_max'])
            if val >= 0.5:
                system_state['stagger_release_max'] = round(val, 1)
                
        broadcast_admin_update()
    except (ValueError, TypeError) as e:
        pass

@socketio.on('admin_reset_simulation')
def handle_admin_reset_simulation():
    system_state['lobby_open'] = False
    system_state['current_phase'] = 1
    system_state['sim_start_time'] = None
    
    for cid, client in list(clients.items()):
        client['product'] = None
        client['product_name'] = None
        client['status'] = 'lobby'
        client['time_x'] = 0.0
        client['start_time'] = None
        client['is_frozen'] = False
        client['will_have_incident'] = False
        client['incident_trigger_time'] = None
        client['freidora_start_time'] = None
        client['delivered_time'] = None
        if client.get('socket_id'):
            socketio.emit('state_change', {'state': 'lobby', 'lobby_open': False}, room=client['socket_id'], namespace='/')
        
    broadcast_admin_update()

@socketio.on('admin_clear_bots')
def handle_admin_clear_bots(data):
    for cid in list(clients.keys()):
        if clients[cid].get('is_bot'):
            del clients[cid]
    broadcast_admin_update()

@socketio.on('admin_simulate_bots')
def handle_admin_simulate_bots(data):
    current_human_count = len([c for c in clients.values() if not c.get('is_bot')])
    bots_to_add = max(0, system_state['max_clients'] - current_human_count)

    # Remove previous bots
    for cid in list(clients.keys()):
        if clients[cid].get('is_bot'):
            del clients[cid]

    lambda_val = system_state['lambda_param']
    
    for i in range(bots_to_add):
        bot_id = f"bot_{int(time.time()*1000)}_{i}"
        
        status = 'lobby'
        prod_name = None
        time_x = 0.0
        
        if system_state['lobby_open']:
            status = 'kitchen_waiting'
            prod_name = '🍔 Bot Burger'
            time_x = generate_exponential_time(lambda_val)
            
        clients[bot_id] = {
            'client_id': bot_id,
            'socket_id': None,
            'is_online': False,
            'name': f"🤖 Bot {i+1}",
            'product': None,
            'product_name': prod_name,
            'status': status,
            'time_x': time_x,
            'start_time': None,
            'is_frozen': False,
            'will_have_incident': False,
            'incident_trigger_time': None,
            'freidora_start_time': None,
            'delivered_time': None,
            'is_bot': True
        }
        
    broadcast_admin_update()
    


@socketio.on('admin_deliver_single')
def handle_admin_deliver_single(data):
    sid = data.get('socket_id')
    
    target_client = None
    for cid, c in clients.items():
        if c.get('socket_id') == sid:
            target_client = c
            break
            
    if target_client:
        client = target_client
        client['status'] = 'phase3_ontime'
        client['is_frozen'] = False
        client['delivered_time'] = round(time.time() - system_state['sim_start_time'], 1) if system_state['sim_start_time'] else client['time_x']
        if client.get('socket_id'):
            socketio.emit('state_change', {
                'state': 'phase3_ontime',
                'student_name': client['name'],
                'product_name': client['product_name'] or '🍕 La Integral',
                'time_x': client['time_x']
            }, room=client['socket_id'], namespace='/')
        broadcast_admin_update()


@app.after_request
def saltar_advertencia_ngrok(response):
    # Añade el header que ngrok exige para no mostrar la pantalla intermedia
    response.headers["ngrok-skip-browser-warning"] = "any_value_here"
    return response

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
