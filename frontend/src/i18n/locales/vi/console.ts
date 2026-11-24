export default {
    table: {
        id: "ID",
        name: "Tên",
        numDay: "Số ngày",
        status: "Trạng thái",
        currentDay: "Ngày hiện tại",
        currentTime: "Giờ hiện tại",
        config: "Cấu hình",
        error: "Lỗi",
        inputTokens: "Token đầu vào",
        outputTokens: "Token đầu ra",
        createdAt: "Ngày tạo",
        updatedAt: "Cập nhật lúc",
        action: "Thao tác"
    },
    statusEnum: {
        "0": "Chưa chạy",
        "1": "Đang chạy",
        "2": "Hoàn tất",
        "3": "Lỗi gián đoạn",
        "4": "Đã dừng"
    },
    buttons: {
        goto: "Mở",
        stop: "Dừng",
        detail: "Chi tiết",
        viewLog: "Xem nhật ký",
        export: "Xuất toàn bộ",
        exportArtifacts: "Xuất kết quả",
        delete: "Xóa",
        createExperiment: "Tạo thí nghiệm"
    },
    modals: {
        experimentDetail: "Chi tiết thí nghiệm",
        experimentLog: "Nhật ký thí nghiệm",
        refresh: "Làm mới",
        manualRefresh: "Làm mới thủ công",
        refreshing: "Đang làm mới...",
        refreshIntervals: {
            oneSecond: "Mỗi 1 giây",
            fiveSeconds: "Mỗi 5 giây",
            tenSeconds: "Mỗi 10 giây",
            thirtySeconds: "Mỗi 30 giây"
        }
    },
    confirmations: {
        stopExperiment: "Bạn có chắc muốn dừng thí nghiệm này không?",
        deleteExperiment: "Bạn có chắc muốn xóa thí nghiệm này không?"
    },
    messages: {
        stopSuccess: "Đã dừng thí nghiệm thành công",
        stopFailed: "Dừng thí nghiệm thất bại:",
        deleteSuccess: "Đã xóa thí nghiệm thành công",
        deleteFailed: "Xóa thí nghiệm thất bại:",
        noToken: "Không tìm thấy token, vui lòng đăng nhập"
    }
};
