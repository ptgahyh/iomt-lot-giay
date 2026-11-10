#!/usr/bin/env bash
# Cài gateway lên Raspberry Pi (hoặc máy Linux họ Debian bất kỳ) để nó tự chạy khi cắm điện.
# Chạy bằng tài khoản thường (script tự gọi sudo khi cần), chạy lại nhiều lần không sao:
#
#     bash gateway/pi/cai_dat.sh
#
# Tùy chọn:
#     --khong-mosquitto   không cài, không đụng tới Mosquitto
#     --khong-dich-vu     không cài dịch vụ systemd (chỉ dựng môi trường Python)
#     --chi-in            chỉ in các lệnh sẽ chạy với sudo, không chạy (để xem trước)
# Mật khẩu chung cho các kẹp tay lấy từ biến môi trường KEP_TAY_PASS; không đặt thì script hỏi.
set -euo pipefail

CO_MOSQUITTO=1
CO_DICH_VU=1
CHI_IN=0
for a in "$@"; do
  case "$a" in
    --khong-mosquitto) CO_MOSQUITTO=0 ;;
    --khong-dich-vu) CO_DICH_VU=0 ;;
    --chi-in) CHI_IN=1 ;;
    *) echo "Không hiểu tùy chọn: $a" >&2; exit 2 ;;
  esac
done

PI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GW_DIR="$(dirname "$PI_DIR")"
NGUOI_DUNG="$(id -un)"
VENV="$GW_DIR/.venv"

if [ "$NGUOI_DUNG" = root ]; then
  echo "Đừng chạy bằng root. Chạy bằng tài khoản thường, script tự gọi sudo." >&2
  exit 2
fi

root() {   # chạy 1 lệnh với quyền root, hoặc chỉ in ra
  if [ "$CHI_IN" = 1 ]; then echo "  sudo $*"; else sudo "$@"; fi
}
buoc() { echo; echo "== $* =="; }
TAM="$(mktemp -d)"
trap 'rm -rf "$TAM"' EXIT

buoc "1/5 Gói hệ thống"
GOI=(python3 python3-venv python3-pip python3-cryptography)
[ "$CO_MOSQUITTO" = 1 ] && GOI+=(mosquitto mosquitto-clients)
root apt-get update
root apt-get install -y "${GOI[@]}"

buoc "2/5 Môi trường Python ở $VENV"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Cần Python 3.11 trở lên (Raspberry Pi OS Bookworm trở đi). Máy này: $(python3 --version)" >&2
  exit 1
fi
# --system-site-packages: dùng luôn python3-cryptography của hệ điều hành, khỏi phải biên dịch trên Pi.
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --quiet -r "$GW_DIR/requirements.txt"
"$VENV/bin/python" -c 'import serial, paho.mqtt, pymodbus, cryptography; print("thư viện Python đủ")'

buoc "3/5 config.toml"
MOI_TAO=0
if [ ! -f "$GW_DIR/config.toml" ]; then
  cp "$GW_DIR/config.example.toml" "$GW_DIR/config.toml"
  chmod 600 "$GW_DIR/config.toml"
  MOI_TAO=1
  echo "đã chép config.example.toml thành config.toml (vẫn là KHÓA THỬ và cổng COM của Windows, phải sửa)"
else
  echo "đã có config.toml, giữ nguyên"
fi

buoc "4/5 Mosquitto (broker cho kẹp tay)"
if [ "$CO_MOSQUITTO" = 1 ]; then
  if [ "$CHI_IN" = 0 ] && sudo test -f /etc/mosquitto/iomt-passwd; then
    echo "đã có /etc/mosquitto/iomt-passwd, giữ nguyên mật khẩu cũ"
  else
    GW_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
    if [ -z "${KEP_TAY_PASS:-}" ]; then
      read -r -s -p "Đặt mật khẩu chung cho các kẹp tay (sẽ điền vào MQTT_PASS của firmware): " KEP_TAY_PASS
      echo
    fi
    [ -n "$KEP_TAY_PASS" ] || { echo "Mật khẩu kẹp tay không được rỗng" >&2; exit 1; }
    if [ "$CHI_IN" = 0 ]; then
      touch "$TAM/passwd"; chmod 600 "$TAM/passwd"
      mosquitto_passwd -b "$TAM/passwd" gateway "$GW_PASS"
      # mỗi kẹp tay một user, tên = id, lấy từ sổ đăng ký trong config.toml
      for id in $("$VENV/bin/python" "$PI_DIR/liet_ke_kep_tay.py" "$GW_DIR/config.toml"); do
        mosquitto_passwd -b "$TAM/passwd" "$id" "$KEP_TAY_PASS"
      done
    fi
    root install -o mosquitto -g mosquitto -m 600 "$TAM/passwd" /etc/mosquitto/iomt-passwd
    # điền mật khẩu gateway vào config.toml (chỉ dòng password trong mục [mqtt])
    if [ "$CHI_IN" = 0 ]; then
      "$VENV/bin/python" "$PI_DIR/liet_ke_kep_tay.py" "$GW_DIR/config.toml" --dat-mat-khau "$GW_PASS"
    fi
    echo "đã tạo user gateway (mật khẩu ngẫu nhiên, đã ghi vào config.toml) và user cho từng kẹp tay"
  fi
  root install -o root -g root -m 644 "$GW_DIR/mosquitto/acl.conf" /etc/mosquitto/iomt-acl.conf
  root install -o root -g root -m 644 "$PI_DIR/mosquitto-iomt.conf" /etc/mosquitto/conf.d/iomt.conf
  root systemctl enable mosquitto
  root systemctl restart mosquitto
else
  echo "bỏ qua"
fi

buoc "5/5 Dịch vụ tự chạy khi bật nguồn"
if [ "$CO_DICH_VU" = 1 ]; then
  root usermod -aG dialout "$NGUOI_DUNG"      # quyền mở /dev/ttyUSB*
  for ten in iomt-gateway iomt-dashboard; do
    sed -e "s|@USER@|$NGUOI_DUNG|g" -e "s|@GW_DIR@|$GW_DIR|g" "$PI_DIR/$ten.service" > "$TAM/$ten.service"
    root install -o root -g root -m 644 "$TAM/$ten.service" "/etc/systemd/system/$ten.service"
  done
  root systemctl daemon-reload
  root systemctl enable iomt-gateway iomt-dashboard
  if [ "$MOI_TAO" = 1 ]; then
    echo "CHƯA khởi động gateway vì config.toml vừa tạo, chưa sửa cổng. Sửa xong chạy:"
    echo "    sudo systemctl restart iomt-gateway iomt-dashboard"
  else
    root systemctl restart iomt-gateway iomt-dashboard
  fi
else
  echo "bỏ qua"
fi

buoc "Xong. Việc còn lại làm bằng tay"
echo "Thiết bị USB nối tiếp đang cắm (dùng đường dẫn này cho port trong config.toml, nó không đổi khi cắm lại):"
find /dev/serial/by-id -mindepth 1 2>/dev/null | sed 's|^|    |' || true
[ -d /dev/serial/by-id ] || echo "    (chưa cắm ESP32 cầu nối hay USB-RS485 nào)"
cat <<TXT
1. nano $GW_DIR/config.toml : sửa [lora] port, [modbus] port, [cloud] token.
2. Sinh khóa thật:  cd $GW_DIR && .venv/bin/python tools/genkeys.py config.toml
3. sudo systemctl restart iomt-gateway iomt-dashboard
4. Xem log:  journalctl -u iomt-gateway -f
5. Bảng điều khiển: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080 (máy cùng mạng Wi-Fi)
Chi tiết: gateway/pi/HUONG-DAN-PI.md
TXT
