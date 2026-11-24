export default {
    balance: 'Số dư',
    recharge: 'Nạp tiền',
    refresh: 'Làm mới',
    refreshSuccess: 'Làm mới thành công',
    autoRefreshOn: 'Đã bật tự động làm mới',
    autoRefreshOff: 'Đã tắt tự động làm mới',
    fetchAccountFailed: 'Không thể lấy thông tin tài khoản',
    confirmRecharge: {
        title: 'Xác nhận nạp tiền',
        content: 'Vui lòng xác nhận các thông tin sau:',
        invited: 'Bạn là người dùng được mời.',
        testing: 'Bạn hiểu rằng hệ thống đang trong giai đoạn thử nghiệm và chưa phát hành chính thức.',
        incomplete: 'Bạn hiểu rằng một số tính năng có thể chưa hoàn chỉnh.',
        changeable: 'Bạn hiểu rằng tính năng và biểu phí có thể thay đổi mà không cần báo trước.',
        okText: 'Xác nhận',
        cancelText: 'Hủy'
    },
    payment: {
        title: 'Thanh toán',
        instruction: 'Vui lòng hoàn tất thanh toán trên trang thanh toán vừa mở',
        openPayment: 'Mở trang thanh toán',
        waiting: 'Đang chờ hoàn tất thanh toán...',
        success: 'Thanh toán thành công',
        failed: 'Thanh toán thất bại',
        timeout: 'Quá thời gian thanh toán',
        checkFailed: 'Kiểm tra trạng thái thanh toán thất bại',
        createFailed: 'Tạo đơn thanh toán thất bại',
        alipayOnly: 'Hiện chỉ hỗ trợ thanh toán qua Alipay',
        refundInvoice: 'Tính năng hoàn tiền và xuất hóa đơn đang phát triển. Vui lòng liên hệ nhân viên nền tảng nếu cần',
        billingItems: 'Hạng mục tính phí gồm token đầu vào LLM (¥3/triệu token), token đầu ra (¥3/triệu token) và thời gian chạy (¥0.001/giây)'
    },
    table: {
        title: 'Chi tiết hóa đơn',
        id: 'ID',
        item: 'Hạng mục',
        related_exp_id: 'ID thí nghiệm liên quan',
        amount: 'Số tiền (CNY)',
        unit_price: 'Đơn giá (CNY)',
        quantity: 'Số lượng',
        description: 'Mô tả',
        createdAt: 'Ngày tạo',
        updatedAt: 'Cập nhật lúc',
        llm_input_token: 'Token đầu vào LLM (triệu token)',
        llm_output_token: 'Token đầu ra LLM (triệu token)',
        run_time: 'Thời gian chạy (giây)',
        recharge: 'Nạp tiền'
    }
};
