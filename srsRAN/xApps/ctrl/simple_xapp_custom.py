#!/usr/bin/env python3
# Importaciones necesarias para el funcionamiento de la xApp
import time
import signal
import argparse
from lib.xAppBase import xAppBase

# Clase principal de la xApp que hereda de xAppBase
class MyXapp(xAppBase):
    def __init__(self, http_server_port, rmr_port):
        super(MyXapp, self).__init__('', http_server_port, rmr_port)

        # Diccionarios para almacenar métricas de cada UE
        self.ue_th_dl = {}            # Throughput de bajada por UE
        self.ue_prb_avail_dl = {}    # PRBs disponibles en DL por UE

        # Parámetros de configuración de ratios de PRBs
        self.min_prb_ratio = 1
        self.max_prb_ratio1 = 10
        self.max_prb_ratio2 = 100
        self.cur_ue_max_prb_ratio = "n/a"

        # Umbrales para detectar congestión
        self.dl_tx_data_max_threshold_kbps = 28500
        self.dl_prb_avail_min_threshold = 15

    # Función de callback ejecutada al recibir datos del nodo E2
    def my_subscription_callback(self, e2_agent_id, subscription_id, indication_hdr,
                                 indication_msg, kpm_report_style, ue_id):
        indication_hdr = self.e2sm_kpm.extract_hdr_info(indication_hdr)
        meas_data = self.e2sm_kpm.extract_meas_data(indication_msg)

        # Procesamiento de datos recibidos por el UE
        for ue_id, ue_meas_data in meas_data["ueMeasData"].items():
            for metric_name, values in ue_meas_data["measData"].items():
                if isinstance(values, list) and len(values) > 0:
                    values = values[0]
                if metric_name == "DRB.UEThpDl":
                    self.ue_th_dl[ue_id] = values
                if metric_name == "RRU.PrbAvailDl":
                    self.ue_prb_avail_dl[ue_id] = values

        # Mostrar métricas recibidas
        for ue_id, ue_meas_data in meas_data["ueMeasData"].items():
            print(f"--UE_id: {ue_id}")
            granulPeriod = ue_meas_data.get("granulPeriod", None)
            if granulPeriod is not None:
                print(f"--- granulPeriod: {granulPeriod}")

            # Procesar las métricas
            for metric_name, values in ue_meas_data["measData"].items():
                print(f"--- Metric: {metric_name}, Value: {values}")
                if isinstance(values, list) and len(values) > 0:
                    values = values[0]  # Tomar el primer valor si es una lista no vacía
                # Evaluar y almacenar las métricas
                if metric_name == "DRB.UEThpDl":
                    self.ue_th_dl[ue_id] = values
                if metric_name == "RRU.PrbAvailDl":
                    self.ue_prb_avail_dl[ue_id] = values

        print("")
        print("Control Logic:")
        print("Tx Data Stats:")

        # Evaluar la condición de congestión
        for ue_id, _ in self.ue_th_dl.items():
            th_dl = self.ue_th_dl.get(ue_id, 0)
            prb_avail_dl = self.ue_prb_avail_dl.get(ue_id, 0)

            # Escenario de Congestión -> Medida de Protección
            if th_dl > self.dl_tx_data_max_threshold_kbps and prb_avail_dl < self.dl_prb_avail_min_threshold:
                new_ue_max_prb_ratio = self.max_prb_ratio1
                if self.cur_ue_max_prb_ratio != self.max_prb_ratio1:
                    previous_prb_ratio = self.cur_ue_max_prb_ratio
                    self.cur_ue_max_prb_ratio = new_ue_max_prb_ratio
                    print(f"-- UE ID: {ue_id}, Max PRB Ratio: {previous_prb_ratio}, Throughput DL: {th_dl}, PRB Avail DL: {prb_avail_dl}")
                    print(f"Congestion detected. Reducing PRB allocation. New Max PRB Ratio: {self.cur_ue_max_prb_ratio}")
                    self.e2sm_rc.control_slice_level_prb_quota(
                        e2_agent_id, ue_id,
                        min_prb_ratio=self.min_prb_ratio,
                        max_prb_ratio=self.cur_ue_max_prb_ratio,
                        dedicated_prb_ratio=100,
                        ack_request=1
                    )

                # Restablecer a más PRB gradualmente
                time.sleep(5)
                print("")
                print("---------------------------- Restoring Capacities ---------------------------------------")
                print("")
                increments = [2, 4, 4, 5]
                for increment in increments:
                    previous_prb_ratio = self.cur_ue_max_prb_ratio
                    self.cur_ue_max_prb_ratio += increment
                    print(f"-- UE ID: {ue_id}, PRB ratio allocation restored to: {self.cur_ue_max_prb_ratio}")
                    self.e2sm_rc.control_slice_level_prb_quota(
                        e2_agent_id, ue_id,
                        min_prb_ratio=self.min_prb_ratio,
                        max_prb_ratio=self.cur_ue_max_prb_ratio,
                        dedicated_prb_ratio=100,
                        ack_request=1
                    )
                    time.sleep(5)

        print("-----------------------------------------")
        print("")

        # Esperar antes de restablecer todos los PRBs al principio
        time.sleep(10)
        previous_prb_ratio = self.cur_ue_max_prb_ratio
        print("---------------------------- Restoring All PRBs to Maximum ---------------------------")
        self.cur_ue_max_prb_ratio = self.max_prb_ratio2  # Asignar todos los PRBs disponibles
        print(f"-- UE ID: {ue_id}, PRB ratio allocation set back to 100%")
        self.e2sm_rc.control_slice_level_prb_quota(
            e2_agent_id, ue_id,
            min_prb_ratio=self.min_prb_ratio,
            max_prb_ratio=self.cur_ue_max_prb_ratio,
            dedicated_prb_ratio=100,
            ack_request=1
        )
        time.sleep(5)  # Tiempo de espera adicional si es necesario
        print("-------------------------------------------")
        print("")

    # Función principal de arranque de la xApp
    @xAppBase.start_function
    def start(self, e2_node_id, kpm_report_style, ue_ids, metric_names):
        report_period = 1000
        granul_period = 1000

        # Crear callback de suscripción
        subscription_callback = lambda agent, sub, hdr, msg: self.my_subscription_callback(
            agent, sub, hdr, msg, kpm_report_style, None
        )

        # Condición para filtrar UEs con baja calidad de señal
        matchingUeConds = [{
            'testCondInfo': {
                'testType': ('ul-rSRP', 'true'),
                'testExpr': 'lessthan',
                'testValue': ('valueInt', 1000)
            }
        }]

        # Realizar la suscripción al nodo
        self.e2sm_kpm.subscribe_report_service_style_4(
            e2_node_id, report_period, matchingUeConds, metric_names,
            granul_period, subscription_callback
        )


# Ejecución principal del script
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--http_server_port", type=int, default=8090)
    parser.add_argument("--rmr_port", type=int, default=4560)
    parser.add_argument("--e2_node_id", type=str, default='gnbd_001_001_00019b_0')
    parser.add_argument("--ran_func_id", type=int, default=2)
    parser.add_argument("--kpm_report_style", type=int, default=4)
    parser.add_argument("--ue_ids", type=str, default='0')
    parser.add_argument("--metrics", type=str, default='DRB.RlcSduTransmittedVolumeDL')

    args = parser.parse_args()
    e2_node_id = args.e2_node_id
    ran_func_id = args.ran_func_id
    ue_ids = list(map(int, args.ue_ids.split(",")))
    kpm_report_style = args.kpm_report_style
    metrics = args.metrics.split(",")

    # Crear e iniciar la xApp
    myXapp = MyXapp(args.http_server_port, args.rmr_port)
    myXapp.e2sm_kpm.set_ran_func_id(ran_func_id)

    # Captura de señales para terminación limpia
    signal.signal(signal.SIGQUIT, myXapp.signal_handler)
    signal.signal(signal.SIGTERM, myXapp.signal_handler)
    signal.signal(signal.SIGINT, myXapp.signal_handler)

    myXapp.start(e2_node_id, kpm_report_style, ue_ids, metrics)
